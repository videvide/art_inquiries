import os
from datetime import datetime, timezone
from flask import Flask, render_template, redirect, flash, request, session
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message, Attachment
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField, FileRequired, FileAllowed, FileSize
from wtforms import StringField
from wtforms.validators import DataRequired, Email, Length, ValidationError
from itsdangerous import URLSafeTimedSerializer
import magic

app = Flask(__name__)
app.secret_key = b"073d57cf645b7846a58e7d1d1dd0ed28f43b43aaacb45296ff37142636d7aded"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///example.sqlite"
app.config["MAIL_PORT"] = "localhost"
app.config["MAIL_PORT"] = 25
app.config["MAIL_USE_TLS"] = False
app.config["MAIL_USE_SSL"] = False
app.config["MAIL_DEBUG"] = app.debug
app.config["MAIL_USERNAME"] = None
app.config["MAIL_PASSWORD"] = None
app.config["MAIL_DEFAULT_SENDER"] = "info@kreddig.io"
app.config["MAIL_MAX_EMAILS"] = None
app.config["MAIL_SUPPRESS_SEND"] = True 
app.config["MAIL_ASCII_ATTACHMENTS"] = False

ITSDANGEROUS_SERIALIZER_KEY = "ec944ccb6a6932fbb5192a207b7d4d22"
ITSDANGEROUS_EMAIL_TOKEN_SALT = "4a898a15174d98e125b0f5a09764e07e"

mail = Mail(app)

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base) # add migration
db.init_app(app)


# lägga till namn på user efter inquiry?
class User(db.Model):
    email: Mapped[str] = mapped_column(primary_key=True, unique=True, default="krajncvide53@gmail.com")
    email_is_confirmed: Mapped[bool] = mapped_column(default=False)
    email_token: Mapped[str] = mapped_column()
    email_token_count: Mapped[int] = mapped_column() # max tre link skick 

    ip_address: Mapped[str] = mapped_column(nullable=True) # make a list 
    inquiry_count: Mapped[int] = mapped_column(default=0)
    

with app.app_context():
    db.create_all()

# compress images with compress png, not much quality loss...
MIN_IMAGE_SIZE = 500000 #0.5MB
MAX_IMAGE_SIZE = 10000000  
MAX_IMAGE_UPLOAD = 5
ALLOWED_FILE_TYPES = ["jpg", "jpeg", "png", "heic"]


# VALIDATE FILE TYPE AND SO ON...
def validate_number_of_images(): # Validates number of files being uploaded
    message = f"Max file upload is {MAX_IMAGE_UPLOAD}!"
    
    def _validate_number_of_images(form, field):
        if len(form.images.data) > MAX_IMAGE_UPLOAD:
            raise ValidationError(message)
    
    return _validate_number_of_images


def validate_images():
    # secure filename här??
    message = ""
    def _validate_images(form, field):
        for image in form.images.data:
            header = image.read(16)
            image.seek(0)
            content_type = magic.from_buffer(header)
            if content_type.split()[0].lower() not in ALLOWED_FILE_TYPES:
                raise ValidationError(f"the file: \n{image.filename} is not an image file.")
        
    return _validate_images     
    

class InquiryForm(FlaskForm):
    name = StringField("name", validators=[DataRequired(), Length(max=50)])
    email = StringField("email", validators=[DataRequired(), Email(), Length(max=50)])
    images = MultipleFileField("images", 
                               validators=[
                                FileRequired(),
                                FileAllowed(["jpg", "jpeg", "png", "heic", "pdf"], "Only specified images types!"),
                               # this only validates file extension
                                FileSize(max_size=MAX_IMAGE_SIZE),
                                validate_number_of_images(),
                                validate_images()])


serializer = URLSafeTimedSerializer(ITSDANGEROUS_SERIALIZER_KEY)
def generate_email_token(email):
    return serializer.dumps(email, salt=ITSDANGEROUS_EMAIL_TOKEN_SALT)


def confirm_email_token(token, max_age=None): # confirmes both token and max_age
    try:
        email = serializer.loads(
            token, salt=ITSDANGEROUS_EMAIL_TOKEN_SALT, max_age=900,
        )
        return email
    except Exception:
        return False


class EmailConfirmationForm(FlaskForm):
    email = StringField("email", validators=[DataRequired(), Email(), Length(max=50)])


def send_confirmation_email(email, token):
    with mail.record_messages() as outbox:
        mail.send_message(subject="confirmation link kreddig.io",
                          body=f"http://localhost:5000/email-confirmation/token/{token}",
                          recipients=[email])
        print(outbox[0])

#resend code countdown on button
@app.route("/email-confirmation", methods=["GET", "POST"])
def email_confirmation():
    form = EmailConfirmationForm()
    if form.validate_on_submit():
        user = db.session.get(User, ident=form.email.data)
        if user and user.email_is_confirmed:
            flash("You're email is already confirmed!")
            return redirect("/email-confirmation")
        
        if user and user.email_token_count <= 3:
            if confirm_email_token(user.email_token):
                flash("Your confirmation link is still valid, check your email!") # lägg till hur länge den är giltig
                return redirect("/email-confirmation")
           
            # allt detta ska köras eller avbrytas
            if user.email_token_count < 3:
                email_token = generate_email_token(user.email)
                user.email_token = email_token
                user.email_token_count += 1
                db.session.commit()

                send_confirmation_email(user.email, email_token)
                flash("Check your email for the new confirmation link!")
                return redirect("/email-confirmation")
            
            flash("You've sent to many requests, contact support")
            return redirect("/email-confirmation")

        email_token = generate_email_token(form.email.data)
        user = User(email=form.email.data, email_token=email_token, email_token_count=1)
        db.session.add(user)
        db.session.commit()
        send_confirmation_email(user.email, email_token)
       
        flash("Check your email for the confirmation link!")
        return redirect("/email-confirmation")
    return render_template("email-confirmation.html", page_title="email confirmation", form=form)




@app.route("/email-confirmation/token/<token>")
def email_confirmation_token(token):
    if token:
        try:
            user = db.session.get(User, ident=confirm_email_token(token))
            user.email_is_confirmed = True
            db.session.commit()
            print(f"user email is confirmed: {user.email_is_confirmed}")
            flash("Thank you for confirming your email!")
            return redirect("/inquiries")
        except Exception:
            # itsdangerous.exc.SignatureExpired: Signature age 121 > 9 seconds
            # itsdangerous.exc.BadTimeSignature: Signature b'4YWVkrUjEn2j80o20HBwBXj9On' does not match
            print(Exception)
    flash("Oops, somethings wrong, please try again!")
    return redirect("/email-confirmation")

# ändra namnen på filerna
#secure filename
def prepare_inquiry_images(images):
    image_attachments = []
    for image in images:
        image_attachments.append(Attachment(filename=secure_filename(image.filename),
                                      content_type=image.content_type,
                                      data=image.read()))
        image.seek(0)
        image.save("output.jpg")
    return image_attachments

def send_inquiry_email(name, email, image_attachments):
    with mail.record_messages() as outbox:
        mail.send_message(subject="inquiry kreddig.io",
                          body=f"hey {name}, this is your inquiry.",
                          attachments=image_attachments,
                          recipients=[email],
                          cc=["info@kreddig.io"])
        print(outbox[0])

@app.route("/inquiries", methods=["GET", "POST"])
def inquiry():
    form = InquiryForm()
    if form.validate_on_submit():
        user = db.session.get(User, ident=form.email.data)
        if user and user.email_is_confirmed:
            if user.inquiry_count < 5:
                send_inquiry_email(name=form.name.data, email=form.email.data, image_attachments=prepare_inquiry_images(form.data["images"]))
                user.inquiry_count += 1
                db.session.commit()
                flash("Your inquiry has been sent!")  
                return redirect("/inquiries")
            flash("It looks like you have sent 5 inquiries already, wait for us to get back to you or contact support.")
            return redirect("/inquiries")
        flash("Oops, it looks like you need to confirm your email, and try again!")
        return redirect("/inquiries")
    return render_template("inquiries.html", page_title="inquiries", form=form)


@app.route("/")
def index():
    return render_template("index.html", page_title="index")


@app.route("/about")
def about():
    return render_template("about.html", page_title="about", data=None)
