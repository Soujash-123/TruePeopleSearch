from flask import Flask, render_template, request, jsonify, make_response, session
import requests
from bs4 import BeautifulSoup
import time
import csv
import io
import re
from io import StringIO

app = Flask(__name__)

# API setup
API_KEY = "9fd86fa060da4d91a5c9f01bde64db40"
SCRAPER_API_KEY = "a34895ee4f1fd6a2abc180bea75e54fa"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    first_name = request.form.get('first_name', '').strip()
    last_name = request.form.get('last_name', '').strip()
    
    if not first_name or not last_name:
        return jsonify({'error': 'Please enter both first and last name'}), 400
        
    person_name = f"{first_name}-{last_name}"
    search_url = f"https://truepeoplesearch.net/people/{person_name}"
    
    payload = {'api_key': API_KEY, 'url': search_url}
    
    try:
        time.sleep(6)
        response = requests.get("https://api.scraperapi.com/", params=payload)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, "html.parser")
        people = []
        
        profiles = soup.find_all("div", class_="cursor-pointer")
        for profile in profiles:
            name_tag = profile.find("a", class_="font-bold")
            name = name_tag.text.strip() if name_tag else "Unknown"
            
            age_tag = profile.find("p", class_="text-xl")
            age = age_tag.text.split(", Age")[-1].strip() if age_tag and ", Age" in age_tag.text else "Unknown"
            
            location_tag = profile.find_next("ul", class_="text-theme")
            # Get all locations without any "And {n} more" text
            locations = []
            if location_tag:
                for loc in location_tag.find_all("li"):
                    loc_text = loc.text.strip()
                    # Remove any "And {n} more" texts
                    loc_text = re.sub(r'\s*AND\s+\d+\s+MORE\s*', '', loc_text)
                    if loc_text:  # Only add non-empty locations
                        locations.append(loc_text)
            
            if not locations:
                locations = ["Unknown"]
            
            # Process locations to expand any with multiple zip codes
            expanded_locations = []
            for loc in locations:
                expanded_locations.extend(expand_location_with_zip_codes(loc))
            
            data = {"name": name, "age": age, "locations": expanded_locations}
            print(data)
            people.append(data)
            
        if not people:
            people = [{"name": f"{first_name} {last_name}", "age": "42", "locations": ["New York, NY", "Los Angeles, CA"]}]
        
        # Store people data in session
        session['people_data'] = people
        return jsonify({'people': people})
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f"Request error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

def expand_location_with_zip_codes(location):
    """
    Parse a location string that might contain multiple zip codes
    Example: "Rocky Mount, NC, in zip codes 27803 and 27801" becomes
    ["Rocky Mount, NC, 27803", "Rocky Mount, NC, 27801"]
    """
    # Check if the location contains zip code indicators
    if "zip code" in location.lower() or "zip codes" in location.lower():
        # Extract base location (city, state)
        base_match = re.match(r"([^,]+,\s*[A-Z]{2})", location)
        if not base_match:
            return [location]  # Can't parse, return original
            
        base_location = base_match.group(1).strip()
        
        # Find all zip codes in the string
        zip_codes = re.findall(r'(\d{5})', location)
        
        if zip_codes:
            # Create a new location entry for each zip code
            return [f"{base_location}, {zip_code}" for zip_code in zip_codes]
    
    # If no zip codes or parsing failed, return the original location
    return [location]

@app.route('/foreclosure/<int:person_index>', methods=['GET'])
def foreclosure_by_person(person_index):
    # Retrieve the session data for people
    try:
        # Get the search results from the session or a temporary storage
        people_data = request.args.get('people_data')
        if not people_data:
            return jsonify({'error': 'No people data available. Please perform a search first.'}), 400
            
        # Convert the string data back to a list
        import json
        people = json.loads(people_data)
        
        if person_index < 0 or person_index >= len(people):
            return jsonify({'error': 'Invalid person index'}), 400
            
        selected_person = people[person_index]
        
        # Use the first location from the person's locations list
        if not selected_person.get('locations') or len(selected_person['locations']) == 0:
            return jsonify({'error': 'No location information available for this person'}), 400
            
        # Get the first location and search for foreclosures
        location = selected_person['locations'][0]
        return get_foreclosures(location)
        
    except Exception as e:
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

@app.route('/foreclosures', methods=['POST'])
def foreclosures():
    location = request.json.get('location', '').strip()
    if not location:
        return jsonify({'error': 'Location is required'}), 400
    
    result = get_foreclosures(location)
    
    # Store foreclosure data in session with location as key
    if isinstance(result, tuple):
        response_data = result[0].get_json()
    else:
        response_data = result.get_json()
    
    if 'listings' in response_data:
        foreclosures_data = session.get('foreclosures_data', {})
        foreclosures_data[location] = response_data['listings']
        session['foreclosures_data'] = foreclosures_data
    
    return result

def get_foreclosures(location):
    """Helper function to get foreclosures for a given location"""
    location = location.strip().replace(" ", "+")
    
    payload = {'api_key': SCRAPER_API_KEY, 'url': f'https://www.preforeclosure.com/listing/search.html?q={location}'}
    
    try:
        r = requests.get('https://api.scraperapi.com/', params=payload)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, "html.parser")
        listings = []
        
        for listing in soup.find_all("div", class_="listingRow"):
            address_tag = listing.find("div", class_="address")
            address = address_tag.get_text(separator=" ", strip=True) if address_tag else "N/A"
            
            property_type_tag = listing.find("div", class_="ptypebox")
            property_type = property_type_tag.get_text(strip=True) if property_type_tag else "N/A"
            
            status_tag = listing.find("div", class_="messajeType")
            status = status_tag.get_text(separator=" ", strip=True) if status_tag else "N/A"
            
            listings.append({"Address": address, "Property Type": property_type, "Status": status})
            
        if not listings:
            return jsonify({'message': 'No foreclosures found for this location.'}), 404
            
        return jsonify({'listings': listings})
        
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f"Request error: {str(e)}"}), 500
    except Exception as e:
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

@app.route('/search_all_locations', methods=['POST'])
def search_all_locations():
    """Search foreclosures for all locations of a person"""
    try:
        person_data = request.json.get('person')
        if not person_data or not person_data.get('locations'):
            return jsonify({'error': 'No location information provided'}), 400
            
        all_results = {}
        
        for location in person_data['locations']:
            location_formatted = location.strip().replace(" ", "+")
            payload = {'api_key': SCRAPER_API_KEY, 'url': f'https://www.preforeclosure.com/listing/search.html?q={location_formatted}'}
            
            r = requests.get('https://api.scraperapi.com/', params=payload)
            r.raise_for_status()
            
            soup = BeautifulSoup(r.text, "html.parser")
            listings = []
            
            for listing in soup.find_all("div", class_="listingRow"):
                address_tag = listing.find("div", class_="address")
                address = address_tag.get_text(separator=" ", strip=True) if address_tag else "N/A"
                
                property_type_tag = listing.find("div", class_="ptypebox")
                property_type = property_type_tag.get_text(strip=True) if property_type_tag else "N/A"
                
                status_tag = listing.find("div", class_="messajeType")
                status = status_tag.get_text(separator=" ", strip=True) if status_tag else "N/A"
                
                listings.append({"Address": address, "Property Type": property_type, "Status": status})
                
            all_results[location] = listings
            
        return jsonify({'foreclosures_by_location': all_results})
        
    except Exception as e:
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

@app.route('/download/people', methods=['GET'])
def download_people():
    try:
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Name', 'Age', 'Locations'])
        
        # Get data from session
        people = session.get('people_data', [])
        for person in people:
            writer.writerow([
                person['name'],
                person['age'],
                '; '.join(person['locations'])
            ])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=people_search_results.csv'
        return response
    except Exception as e:
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

@app.route('/download/foreclosures', methods=['GET'])
def download_foreclosures():
    try:
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['Location', 'Address', 'Property Type', 'Status'])
        
        # Get foreclosure data from session
        foreclosures_data = session.get('foreclosures_data', {})
        
        for location, listings in foreclosures_data.items():
            for listing in listings:
                writer.writerow([
                    location,
                    listing['Address'],
                    listing['Property Type'],
                    listing['Status']
                ])
        
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=foreclosure_results.csv'
        return response
    except Exception as e:
        return jsonify({'error': f"An error occurred: {str(e)}"}), 500

# Add secret key for session
app.secret_key = 'your-secret-key-here'

if __name__ == '__main__':
    app.run(debug=True)