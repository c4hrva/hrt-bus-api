from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for
from geopy import geocoders
import json
import os
import pymongo

app = Flask(__name__)
db = pymongo.Connection(os.environ['MONGO_URI']).hrt
dthandler = lambda obj: obj.isoformat() if isinstance(obj, datetime) else None

curDateTime  = datetime.utcnow() + timedelta(hours=-5)
collectionPrefix = curDateTime.strftime('%Y%m%d')

@app.before_request
def beforeRequest():
	curDateTime  = datetime.utcnow() + timedelta(hours=-5)
	collectionPrefix = curDateTime.strftime('%Y%m%d')

@app.route('/')
def index():
    return redirect(url_for('busfinder'))

@app.route('/busfinder/')
@app.route('/busfinder/<path:view>/')
def busfinder(view=None):
	return render_template('busfinder.html')

@app.route('/api/routes/active/')
def getActiveRoutes():
	# List the routes from the checkins
	activeRoutes = db['checkins'].find({'location': {'$exists': True}}).distinct('routeId')
	
	# Get details about those routes from the GTFS data
	activeRoutesWithDetails = db['routes_' + collectionPrefix].find({'route_id': {'$in': activeRoutes}}, fields={'_id': False}).sort('route_id')
	return json.dumps(list(activeRoutesWithDetails))

@app.route('/api/buses/on_route/<int:routeId>/')
def getBusesOnRoute(routeId):
	# Get all checkins for the route, only keep the last one for each bus
	checkins = {}
	for checkin in db['checkins'].find({'routeId':routeId, 'location': {'$exists': True}}, fields={'_id': False}).sort('time'):
		checkins[checkin['busId']] = checkin
	return json.dumps(checkins.values(), default=dthandler)
	
@app.route('/api/buses/history/<int:busId>/')
def getBusHistory(busId):
	# Get all checkins for a bus
	checkins = db['checkins'].find({'busId':busId, 'location': {'$exists': True}}, fields={'_id': False, 'tripId': False}).sort('time', pymongo.DESCENDING)
	return json.dumps(list(checkins), default=dthandler)

@app.route('/api/stops/near/intersection/<city>/<intersection>/')
def getStopsNearIntersection(city, intersection):
	geocoders.Google()
	place, (lat, lng) = geocoders.Google().geocode("{0}, {1}, VA".format(intersection, city), exactly_one=False)[0]
	return getStopsNear(lat, lng)

@app.route('/api/stops/near/<lat>/<lng>/')
def getStopsNear(lat, lng):
	stops = db['stops_' + collectionPrefix].find({"location": {"$near": [float(lng), float(lat)]}}, fields={'_id': False}).limit(6)
	stops = list(stops)
	
	for stop in stops:
		inboundRoutes =  db['gtfs_' + collectionPrefix].find({"stop_id": stop['stopId'], "direction_id": 1}).distinct('route_id')
		outboundRoutes = db['gtfs_' + collectionPrefix].find({"stop_id": stop['stopId'], "direction_id": 0}).distinct('route_id')
		stop['inboundRoutes'] =  list(db['routes_' + collectionPrefix].find({'route_id': {'$in': inboundRoutes}}, fields={'_id': False}).sort('route_id'))
		stop['outboundRoutes'] = list(db['routes_' + collectionPrefix].find({'route_id': {'$in': outboundRoutes}}, fields={'_id': False}).sort('route_id'))
	return json.dumps(stops)

@app.route('/api/stop_times/<int:routeId>/<int:stopId>/')
def getNextBus(routeId, stopId):
	scheduledStops = db['gtfs_' + collectionPrefix].find({'route_id':routeId, 'stop_id':stopId, 'arrival_time': {'$gte': datetime.utcnow()}}).sort('arrival_time').limit(3)
	lastStop = db['gtfs_' + collectionPrefix].find({'route_id':routeId, 'stop_id':stopId, 'arrival_time': {'$lt': datetime.utcnow()}}).sort('arrival_time', pymongo.DESCENDING).limit(1)
	data = list(lastStop)
	data += list(scheduledStops)
	for stop in data:
		stop['all_trip_ids'] = list(db['gtfs_' + collectionPrefix].find({'block_id': stop['block_id']}).distinct('trip_id'))
		checkins = db['checkins'].find({'tripId': {'$in': stop['all_trip_ids']}}).sort('time', pymongo.DESCENDING)
		for checkin in checkins:
			try:
				stop['adherence'] = checkin['adherence']
				stop['busId'] = checkin['busId']
				break
			except KeyError:
				pass
	return json.dumps(data, default=dthandler)

if __name__ == '__main__':
    # Bind to PORT if defined, otherwise default to 5000.
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
