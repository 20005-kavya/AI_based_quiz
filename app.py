from flask import Flask, render_template, request, redirect, session
from groq import Groq
from pymongo import MongoClient
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer
import os
import smtplib
import pandas as pd
import json
import bcrypt
import fitz

load_dotenv()

app = Flask(__name__)
app.secret_key = "quiz_secret"
serializer = URLSafeTimedSerializer(app.secret_key)

# CONFIG
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
EMAIL = os.getenv("EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
MONGO_URI = os.getenv("MONGO_URI")

# LOCAL DATABASE CONNECTION
try:

    # mongo_client = MongoClient("mongodb://localhost:27017/")
    mongo_client = MongoClient(MONGO_URI)

    db = mongo_client["quizdb"]

    users = db["users"]
    results = db["results"]

    print("✅ MongoDB Local Connection Successful")

except Exception as e:

    print("❌ MongoDB Connection Failed")
    print(e)

# GROQ CLIENT
client = Groq(api_key=GROQ_API_KEY)

# AI QUIZ GENERATOR
def generate_quiz(topic):

    prompt = f"""
Generate 30 MCQ questions on {topic}.

Return ONLY JSON in this format:

[
{{
"question":"What is Python?",
"A":"Language",
"B":"Animal",
"C":"Car",
"D":"Game",
"answer":"A",
"topic":"Basics"
}}
]

Each question MUST include a "topic" field.

No extra text.
"""

    chat = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.3-70b-versatile"
    )

    quiz_text = chat.choices[0].message.content

    #FIX HERE
    # quiz_json = json.loads(quiz_text.strip())
    try:
         quiz_json = json.loads(quiz_text.strip())
    except:
         print("JSON Error:", quiz_text)
         quiz_json = []

    return quiz_json

# EMAIL FUNCTION
def send_email(to_email, text):

    server = smtplib.SMTP("smtp.gmail.com",587)
    server.starttls()

    server.login(EMAIL, EMAIL_PASSWORD)

    message = f"Subject: Quiz Result\n\n{text}"

    server.sendmail(EMAIL,to_email,message)

    server.quit()


# ANALYSIS
# def analyze_topic(score):

#     data = {
#         "Topic":["OOPS","Inheritance","Polymorphism","Encapsulation"],
#         "Score":[score,score-10,score-20,score+5]
#     }

#     df = pd.DataFrame(data)

#     weak = df[df["Score"]<60]["Topic"].tolist()

#     return weak

# PDF TO TEXT
def pdf_to_text(file):

    doc = fitz.open(file)

    text = ""

    for page in doc:
        text += page.get_text()

    return text


# LOGIN
@app.route("/", methods=["GET","POST"])
def login():

    error = None

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        user = users.find_one({"email": email})

        if not user:
            error = "Email not found"

        else:
            stored_password = user["password"]

            if bcrypt.checkpw(password.encode("utf-8"), stored_password):

                session["user"] = email
                session["username"] = user["username"]
                return redirect("/dashboard")

            else:
                error = "Wrong Password"

    return render_template("login.html", error=error)


# SIGNUP
@app.route("/signup", methods=["GET","POST"])
def signup():

    if request.method == "POST":

        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        # Hash password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        users.insert_one({
            "username": username,
            "email": email,
            "password": hashed_password
        })

        return redirect("/")

    return render_template("signup.html")

# LOGOUT
@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")

# FORGOT PASSWORD
@app.route("/forgot", methods=["GET","POST"])
def forgot():

    if request.method == "POST":

        email = request.form["email"]
        user = users.find_one({"email": email})

        if user:

            token = serializer.dumps(email, salt="reset-password")

            reset_link = f"https://ai-quizgenerate.onrender.com/reset/{token}"

            message = f"""
Subject: Password Reset

Click the link below to reset your password:

{reset_link}

This link expires in 10 minutes.
"""

            server = smtplib.SMTP("smtp.gmail.com",587)
            server.starttls()
            server.login(EMAIL, EMAIL_PASSWORD)

            server.sendmail(EMAIL, email, message)
            server.quit()

            return "Reset link sent to your email"

        else:
            return "Email not found"

    return render_template("forgot.html")

# RESET PASSWORD
@app.route("/reset/<token>", methods=["GET","POST"])
def reset_password(token):

    try:
        email = serializer.loads(token, salt="reset-password", max_age=600)
    except:
        return "Reset link expired"

    if request.method == "POST":

        new_password = request.form["password"]

        hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt())

        users.update_one(
            {"email": email},
            {"$set": {"password": hashed}}
        )

        return redirect("/")

    return render_template("reset_password.html")

# DASHBOARD
# @app.route("/dashboard",methods=["GET","POST"])
# def dashboard():

#     quiz=""

#     if request.method=="POST":

#         topic=request.form["topic"]

#         quiz=generate_quiz(topic)

#         session["quiz"]=quiz

#     return render_template("dashboard.html",quiz=quiz)

@app.route("/dashboard", methods=["GET","POST"])
def dashboard():

    if "user" not in session:
        return redirect("/")

    if request.method == "POST":
        topic = request.form["topic"]
        quiz = generate_quiz(topic)

        session["quiz"] = quiz
        session["topic"] = topic

        return redirect("/quiz")

    return render_template("dashboard.html")

# LEADERBOARD
@app.route("/leaderboard")
def leaderboard():

    pipeline = [
        {
            "$group":{
                "_id":"$email",
                "username":{"$first":"$username"},
                "score":{"$max":"$score"},
                "topic":{"$last":"$topic"}
            }
        },
        {"$sort":{"score":-1}}
    ]

    data = list(results.aggregate(pipeline))

    return render_template("leaderboard.html", data=data)

# ANALYTICS
@app.route("/analytics")
def analytics():

    email = session["user"]

    user_results = list(results.find({"email":email}))

    scores = [r["score"] for r in user_results]

    attempts = len(scores)

    avg_score = sum(scores)/attempts if attempts>0 else 0

    weak_topics = []

    for r in user_results:
        weak_topics.extend(r["weak_topics"])

    return render_template(
        "analytics.html",
        attempts=attempts,
        avg=avg_score,
        weak=weak_topics
    )

# PDF UPLOAD
@app.route("/pdf_quiz", methods=["GET","POST"])
def pdf_quiz():

    if request.method == "POST":

        file = request.files["pdf"]

        filepath = "temp.pdf"

        file.save(filepath)

        text = pdf_to_text(filepath)

        quiz = generate_quiz(text[:2000])

        session["quiz"] = quiz

        return redirect("/quiz")

    return render_template("pdf_upload.html")

# QUIZ PAGE
@app.route("/quiz")
def quiz():

    quiz = session.get("quiz")

    if not quiz:
        return redirect("/dashboard")

    return render_template("quiz.html", quiz=quiz)

# QUIT QUIZ
@app.route("/quit_quiz")
def quit_quiz():

    session.pop("quiz", None)

    return redirect("/dashboard")

# SUBMIT RESULT
@app.route("/submit", methods=["POST"])
def submit():

    quiz = session.get("quiz")

    score = 0
    topic_performance = {}

    for i, q in enumerate(quiz):

        user_ans = request.form.get(f"q{i}")
        correct_ans = q["answer"]
        topic = q.get("topic", "General")

        # Initialize topic
        if topic not in topic_performance:
            topic_performance[topic] = {"correct": 0, "total": 0}

        topic_performance[topic]["total"] += 1

        if user_ans == correct_ans:
            score += 1
            topic_performance[topic]["correct"] += 1

    percent = int((score / len(quiz)) * 100)

    # ✅ REAL WEAK TOPIC LOGIC
    weak_topics = []

    for t, data in topic_performance.items():
        accuracy = (data["correct"] / data["total"]) * 100

        if accuracy < 60:
            weak_topics.append(t)

    email = session["user"]

    # SAVE RESULT
    results.insert_one({
        "email": email,
        "username": session.get("username"),
        "topic": session.get("topic"),
        "score": percent,
        "weak_topics": weak_topics,
        "topic_performance": topic_performance  # bonus
    })

    # EMAIL
    result_text = f"""
Score: {percent}%

Weak Topics:
{weak_topics}
"""

    send_email(email, result_text)

    session.pop("quiz", None)

    return redirect("/dashboard")

# @app.route("/submit", methods=["POST"])
# def submit():

#     quiz = session.get("quiz")

#     score = 0
#     correct_answers = []

#     for i, q in enumerate(quiz):

#         user_ans = request.form.get(f"q{i}")

#         if user_ans == q["answer"]:
#             score += 1
#             correct_answers.append(True)
#         else:
#             correct_answers.append(False)

#     percent = int((score / len(quiz)) * 100)

#     email = session["user"]

#     weak_topics = analyze_topic(percent)

#     result_text = f"""
# Score: {percent}%

# Correct Answers: {score}/30

# Weak Topics:
# {weak_topics}
# """

#     results.insert_one({
#         "email": email,
#         "score": percent,
#         "weak_topics": weak_topics
#     })

#     send_email(email, result_text)

#     session.pop("quiz", None)

#     return render_template(
#         "result.html",
#         score=percent,
#         correct=score
#     )

# RESULTS PAGE
@app.route("/results")
def results_page():

    email = session["user"]

    user_results = list(results.find({"email": email}))

    return render_template(
        "results.html",
        data=user_results
    )

if __name__=="__main__":
    # app.run(host='0.0.0.0', port=7860)
    app.run(debug=True)