from django.contrib import admin
from django.urls import include, path

from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/signup/', views.signup, name='signup'),
    path('', views.home, name='home'),
    path('lehrkraefte/', views.teacher_list, name='teacher_list'),
    path('lehrkraefte/<slug:slug>/', views.teacher_detail, name='teacher_detail'),
    path('lehrkraefte/<slug:slug>/bewerten/', views.rate_teacher, name='rate_teacher'),
    path('ranking/', views.ranking, name='ranking'),
    path('ranking/_partial/', views.ranking_partial, name='ranking_partial'),
    path('achievements/', views.achievements, name='achievements'),
    path('achievements/<slug:slug>/', views.achievement_detail, name='achievement_detail'),
]
