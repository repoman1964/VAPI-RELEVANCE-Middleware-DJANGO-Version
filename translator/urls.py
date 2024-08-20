from django.urls import path
from . import views

urlpatterns = [
    path('server/messages/', views.handleVAPIServerMessages, name='vapi_messages'),

    path('chat/completions', views.chat_completions, name='chat_completions'),

    path('create-transient/', views.createTransientAssistant, name='create_transient'),
]