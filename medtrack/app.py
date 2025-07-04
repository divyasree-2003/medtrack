"""
Flask + AWS DynamoDB + SNS demo
Author: <you>
"""

import os, uuid, json
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
import boto3
from botocore.exceptions import ClientError

# ──────────────────────────────
# ░░  Flask Setup
# ──────────────────────────────
app = Flask(__name__)
app.secret_key = "change_this_to_a_long_random_string"

# ──────────────────────────────
# ░░  AWS clients (DynamoDB & SNS)
# ──────────────────────────────
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")          # <— use your region
USERS_TABLE        = "Users"
APPOINTMENTS_TABLE = "Appointments"
SNS_TOPIC_ARN      = os.getenv("SNS_TOPIC_ARN")             # set this after creating the topic

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
sns       = boto3.client("sns",     region_name=AWS_REGION)

users_table        = dynamodb.Table(USERS_TABLE)
appointments_table = dynamodb.Table(APPOINTMENTS_TABLE)

# ──────────────────────────────
# ░░  Routes
# ──────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about-us")
def aboutus():
    return render_template("aboutus.html")


@app.route("/contact-us", methods=["GET", "POST"])
def contactus():
    if request.method == "POST":
        return render_template("thankyou.html", name=request.form["name"])
    return render_template("contactus.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        fullname         = request.form.get("fullname")
        email            = request.form.get("email")
        password         = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        # basic validation
        if not fullname or not email or not password or not confirm_password:
            flash("All fields are required.");  return redirect(url_for("signup"))
        if password != confirm_password:
            flash("Passwords do not match.");  return redirect(url_for("signup"))

        # save / overwrite user record
        try:
            users_table.put_item(
                Item={
                    "email": email,
                    "fullname": fullname,
                    "password": password,  # ❗️store hashes in prod!
                    "created_at": datetime.utcnow().isoformat()
                }
            )
            flash("Signup successful! Please log in.")
            return redirect(url_for("login"))
        except ClientError as e:
            flash(f"Error saving user: {e.response['Error']['Message']}")
            return redirect(url_for("signup"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email")
        password = request.form.get("password")

        # fetch user
        try:
            resp = users_table.get_item(Key={"email": email})
            user = resp.get("Item")
        except ClientError as e:
            flash("Error accessing database.");  return redirect(url_for("login"))

        if not user or user["password"] != password:
            flash("Invalid credentials.");  return redirect(url_for("login"))

        session["user"] = user["fullname"]
        session["email"] = email
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", user=session["user"])


@app.route("/create-appointment", methods=["GET", "POST"])
def create_appointment():
    if "user" not in session:
        flash("Please log in to book an appointment.")
        return redirect(url_for("login"))

    if request.method == "POST":
        doctor   = request.form.get("doctor")
        date     = request.form.get("date")
        time     = request.form.get("time")
        symptoms = request.form.get("symptoms")

        # ── 1.  Save appointment in DynamoDB
        appointment_id = str(uuid.uuid4())
        try:
            appointments_table.put_item(
                Item={
                    "appointment_id": appointment_id,
                    "email": session["email"],
                    "doctor": doctor,
                    "date": date,
                    "time": time,
                    "symptoms": symptoms,
                    "created_at": datetime.utcnow().isoformat()
                }
            )
        except ClientError as e:
            flash("DB error while booking appointment.")
            return redirect(url_for("create_appointment"))

        # ── 2.  Publish SNS confirmation
        if SNS_TOPIC_ARN:
            msg = {
                "appointment_id": appointment_id,
                "user": session["user"],
                "doctor": doctor,
                "date": date,
                "time": time
            }
            try:
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Subject="New Appointment Booked",
                    Message=json.dumps(msg, indent=2)
                )
            except ClientError as e:
                # don’t block user; just log/flash if needed
                app.logger.error(f"SNS publish failed: {e}")

        return render_template(
            "appointment_status.html",
            doctor=doctor, date=date, time=time, symptoms=symptoms
        )

    return render_template("appointment.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("home"))


if __name__ == "__main__":
    # debug=True for local dev only
    app.run(debug=True, port=5000)
