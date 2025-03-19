from django.urls import path
from .views import create_trip, generate_logsheet, get_trip_log

urlpatterns = [
    path('create_trip/', create_trip, name='create_trip'),
    path('logsheet/', generate_logsheet, name='generate_logsheet'),
    path('trip_log/<int:trip_id>/', get_trip_log, name='get_trip_log'),
]