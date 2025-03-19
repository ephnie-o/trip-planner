# from django.shortcuts import render
# import logging
# from rest_framework import generics
from .models import Trip, Stop, TripStatus
from .serializers import TripSerializer, StopSerializer
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.http import HttpResponse
import requests
from io import BytesIO
from reportlab.pdfgen import canvas
import logging
from datetime import datetime, timedelta
import os
from django.conf import settings
from reportlab.lib import utils

logger = logging.getLogger(__name__)

# Create your views here.
@api_view(['POST'])
def create_trip(request):
    """
    Creates a Trip instance, calculates the route and stops.
    Expects JSON with:
      - current_location: "lat,lon"
      - pickup_location: "lat,lon"
      - dropoff_location: "lat,lon"
      - current_cycle_used: number
    """
    # Extract and validate data from the request
    current_location = request.data.get('current_location')
    current_location_address = request.data.get('current_location_address')
    pickup_location = request.data.get('pickup_location')
    pickup_address = request.data.get('pickup_address')
    dropoff_location = request.data.get('dropoff_location')
    dropoff_address = request.data.get('dropoff_address')
    current_cycle_used = request.data.get('current_cycle_used', 0)

    if not current_location or not pickup_location or not dropoff_location:
        return Response({"error": "Missing required fields."}, status=400)

    # Create a Trip record
    trip = Trip.objects.create(
        current_location=current_location,
        current_location_address=current_location_address,
        pickup_location=pickup_location,
        pickup_address=pickup_address,
        dropoff_location=dropoff_location,
        dropoff_address=dropoff_address,
        current_cycle_used=current_cycle_used,
    )

    # Parse coordinate strings ("lat,lon")
    try:
        curr_lat, curr_lon = map(float, current_location.split(','))
        pick_lat, pick_lon = map(float, pickup_location.split(','))
        drop_lat, drop_lon = map(float, dropoff_location.split(','))
    except Exception as e:
        logger.exception("Coordinate parsing error:")
        return Response({"error": "Invalid coordinate format. Use 'lat,lon'."}, status=400)

    # Build the OSRM API request
    # OSRM expects coordinates in lon,lat order
    coordinates = f"{curr_lon},{curr_lat};{pick_lon},{pick_lat};{drop_lon},{drop_lat}"
    osrm_url = f"http://router.project-osrm.org/route/v1/driving/{coordinates}?overview=full&geometries=geojson"

    try:
        route_response = requests.get(osrm_url)
        route_response.raise_for_status()
        route_data = route_response.json()
    except Exception as e:
        logger.exception("Error fetching route from OSRM:")
        return Response({"error": f"Failed to fetch route from OSRM: {str(e)}"}, status=500)

    try:
        route_data = route_response.json()
        if not route_data.get('routes'):
            raise ValueError("No routes found in OSRM response.")
    except Exception as e:
        logger.exception("Error processing OSRM response:")
        return Response({"error": f"Error processing OSRM response: {str(e)}"}, status=500)


    # Extract route details
    route_geometry = route_data['routes'][0]['geometry']
    total_distance_m = route_data['routes'][0]['distance']
    total_distance_miles = total_distance_m * 0.000621371  # Convert meters to miles

    # Update the Trip record with route details
    trip.route_geometry = route_geometry
    trip.total_distance_miles = total_distance_miles
    trip.save()

    # Calculate fueling stops (1 stop per 1000 miles)
    threshold = 1000
    fueling_stops = int(total_distance_miles // threshold)
    route_coords = route_geometry.get('coordinates', [])  # List of [lon, lat]
    # Create a list to keep track of stops (optional, as we’re saving them to the DB)
    stops_data = []

    if fueling_stops > 0 and len(route_coords) > fueling_stops:
        step = len(route_coords) // (fueling_stops + 1)
        for i in range(1, fueling_stops + 1):
            point = route_coords[i * step]
            stop = Stop.objects.create(
                trip=trip,
                type="Fuel",
                location_lat=point[1],
                location_lon=point[0],
                duration_minutes=30  # Assumed fueling duration
            )
            stops_data.append(stop)
    
    # Create pickup and dropoff stops (each with 1 hour duration)
    pickup_stop = Stop.objects.create(
        trip=trip,
        type="Pickup",
        location_lat=pick_lat,
        location_lon=pick_lon,
        duration_minutes=60
    )
    dropoff_stop = Stop.objects.create(
        trip=trip,
        type="Dropoff",
        location_lat=drop_lat,
        location_lon=drop_lon,
        duration_minutes=60
    )
    # Optionally, add these to the stops list (for ordering, etc.)
    stops_data.insert(0, pickup_stop)
    stops_data.append(dropoff_stop)
    
    TripStatus.objects.create(
    trip=trip,
    status='OFF_DUTY',
    start_time=datetime.now().time(),
    end_time=(datetime.now() + timedelta(hours=4)).time(),
    location=pickup_address
    )

    TripStatus.objects.create(
        trip=trip,
        status='DRIVING',
        start_time=(datetime.now() + timedelta(hours=4)).time(),
        end_time=(datetime.now() + timedelta(hours=6)).time(),
        location=dropoff_address
    )
    
    # Return the serialized Trip with nested stops
    serializer = TripSerializer(trip)
    return Response(serializer.data)

def wrap_text(p, text, x, y, max_width):
    """
    Wraps text to a given width in ReportLab.
    """
    if len(text) <= max_width // 6:  # Approximate character width in pixels
        p.drawString(x, y, text)  # No need to wrap if text fits

    else:
        lines = []
        words = text.split(' ')
        current_line = ""

        for word in words:
            if p.stringWidth(current_line + word) < max_width:
                current_line += word + " "
            else:
                lines.append(current_line.strip())
                current_line = word + " "
        lines.append(current_line.strip())  # Append the remaining text

        # Draw each line
        for i, line in enumerate(lines):
            p.drawString(x, y - (i * 15), line)  # Each line moves 15px down

@api_view(['GET','POST'])
def generate_logsheet(request):
    """
    Generates a PDF log sheet for a given trip.
    Accepts trip_id as a query parameter for GET requests or in JSON for POST requests.
    """
    if request.method == 'GET':
        trip_id = request.query_params.get('trip_id')
    else:
        trip_id = request.data.get('trip_id')

    if not trip_id:
        return Response({"error": "trip_id is required."}, status=400)

    try:
        trip = Trip.objects.get(id=trip_id)
        statuses = TripStatus.objects.filter(trip=trip).order_by('start_time')
    except Trip.DoesNotExist:
        return Response({"error": "Trip not found."}, status=404)

    # Get today's date fields
    now = datetime.now()
    day = now.day
    month = now.month
    year = now.year

    # Create a PDF using ReportLab
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=(800, 600))

    image_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'blank-paper-log.png')
    p.drawImage(image_path, 0, 0, width=800, height=600)

    page_height = 600

    # Title and basic trip info
    p.setFont("Helvetica-Bold", 12)
    # Date (positioned at 20px from top, left 150px)
    p.drawString(310, page_height - 20, f"{month}      {day}                {year}")
    # Cycle Hours (50px from top)
    p.drawString(120, page_height - 520, f"{trip.current_cycle_used}")
    # Total Distance (80px from top)
    p.drawString(100, page_height - 90, f"{trip.total_distance_miles:.2f} miles")
    # Use the address fields instead of raw coordinates:
    wrap_text(p, f"{trip.current_location_address}", 150, page_height - 50, 250)
    wrap_text(p, f"Pickup location: {trip.pickup_address}", 250, page_height - 400, 250)
    wrap_text(p, f"{trip.dropoff_address}", 450, page_height - 50, 250)

    # 🚨 Draw Timeline Graph (Main Logic)
    def get_time_position(time_str):
        """Convert 'HH:MM' format to X-coordinate (pixels)"""
        hour, minute = map(int, time_str.split(':'))
        return 63 + (hour + minute / 60) * 30

    def get_y_position(status):
        """Map status to corresponding Y-coordinate on the log sheet"""
        status_y_positions = {
            'OFF_DUTY': 380,
            'SLEEPER': 315,
            'DRIVING': 340,
            'ON_DUTY': 265
        }
        return status_y_positions.get(status, 0)

    # Draw each status on the timeline
    p.setStrokeColor('black')
    p.setLineWidth(2)
    p.setFillColor('red')

    for status in statuses:
        if not status.start_time or not status.end_time:
            continue  # Skip invalid data

        start_x = get_time_position(status.start_time.strftime('%H:%M'))
        end_x = get_time_position(status.end_time.strftime('%H:%M'))
        y_position = get_y_position(status.status)

        # Draw Line
        p.line(start_x, y_position, end_x, y_position)

        # Draw Red Dots
        p.circle(start_x, y_position, 3, stroke=1, fill=1)
        p.circle(end_x, y_position, 3, stroke=1, fill=1)

        # Status Label for Visibility
        p.setFont("Helvetica", 8)
        p.drawString(start_x + 5, y_position - 8, status.status)

    # List out the stops with details
    y = page_height - 310
    for stop in trip.stops.all():
        stop_text = f"{stop.type} at {stop.duration_minutes} min"  # Adjust as needed
        p.drawString(150, y, stop_text)
        y -= 20

    p.showPage()
    p.save()
    buffer.seek(0)

    # Return the PDF as an HTTP response
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="logsheet_trip_{trip.id}.pdf"'
    return response

@api_view(['GET'])
def get_trip_log(request, trip_id):
    try:
        trip = Trip.objects.get(id=trip_id)
        statuses = TripStatus.objects.filter(trip=trip).order_by('start_time')

        data = {
            "trip_id": trip.id,
            "pickup_location": trip.pickup_address,
            "dropoff_location": trip.dropoff_address,
            "total_distance_miles": trip.total_distance_miles,
            "current_cycle_used": trip.current_cycle_used,
            "statuses": [
                {
                    "status": status.status,
                    "start_time": status.start_time.strftime('%H:%M') if status.start_time else "00:00",
                    "end_time": status.end_time.strftime('%H:%M') if status.end_time else "00:00",
                    "location": status.location
                }
                for status in statuses
            ]
        }

        return Response(data)

    except Trip.DoesNotExist:
        return Response({"error": "Trip not found."}, status=404)
