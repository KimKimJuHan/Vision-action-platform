from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=False, label="이메일(선택)")

    class Meta:
        model = User
        fields = ("username", "email")
