"""회원가입은 직접 작성하고, 로그인·로그아웃은 Django 기본 인증 뷰를 연결한다 (커스텀 User 없음)."""
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import SignupForm


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("analyses:index")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()  # 비밀번호는 해시로 auth_user에 저장
        login(request, user)
        return redirect("analyses:index")
    return render(request, "accounts/signup.html", {"form": form})
