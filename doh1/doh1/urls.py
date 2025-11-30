from django.contrib import admin
from django.urls import path
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('update-cookies/', views.update_cookies, name='update_cookies'),
    path('run/', views.execute_report, name='execute_report'),
    path('logout/', views.logout_view, name='logout'),
    path('report/execute/', views.execute_report, name='execute_report'),
    path('report/view/', views.view_report_results, name='view_report_results'),
]