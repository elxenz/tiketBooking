# app.py
from flask import Flask, render_template, request, redirect, url_for, flash
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
from functools import wraps

app = Flask(__name__)
# Ganti dengan secret key yang kuat dan ambil dari variabel lingkungan saat deployment
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a-very-strong-and-unique-secret-key-for-dev-123!")

# --- Konfigurasi MongoDB ---
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client['booking_tiket_db']
users_collection = db['users']
flights_collection = db['flights']
bookings_collection = db['bookings']

# --- Konfigurasi Flask-Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Anda harus login untuk mengakses halaman ini."
login_manager.login_message_category = "info"

# --- Model Pengguna & Peran ---
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']
        self.email = user_data['email']
        self.password_hash = user_data['password']
        self.role = user_data.get('role', 'user')

    def is_admin(self):
        return self.role == 'admin'

@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = users_collection.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(user_data)
    except Exception as e:
        app.logger.error(f"Error loading user: {e}")
    return None

# Decorator untuk halaman yang memerlukan hak akses admin
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Halaman ini hanya dapat diakses oleh Admin.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- Fungsi Pembantu & Konteks Global ---
def get_unique_airports():
    try:
        origins = flights_collection.distinct('origin')
        destinations = flights_collection.distinct('destination')
        all_airports = sorted(list(set(origins + destinations)))
        return all_airports
    except Exception as e:
        app.logger.error(f"Error getting unique airports: {e}")
        return []

@app.context_processor
def inject_global_vars():
    """Menyediakan variabel global ke semua template."""
    return {
        'current_year': datetime.now().year
    }

# --- Rute Autentikasi ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Konfirmasi password tidak cocok!', 'error')
            return redirect(url_for('register'))

        if users_collection.find_one({'$or': [{'username': username}, {'email': email}]}):
            flash('Username atau email sudah digunakan!', 'error')
            return redirect(url_for('register'))

        # Jadikan user pertama sebagai admin, sisanya user biasa
        role = 'admin' if users_collection.count_documents({}) == 0 else 'user'

        users_collection.insert_one({
            'username': username,
            'email': email,
            'password': generate_password_hash(password),
            'role': role,
            'created_at': datetime.now()
        })
        flash(f'Registrasi berhasil! Akun Anda terdaftar sebagai {role}. Silakan login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user_data = users_collection.find_one({'username': username})

        if user_data and check_password_hash(user_data['password'], password):
            user = User(user_data)
            login_user(user)
            flash(f'Selamat datang kembali, {user.username}!', 'success')
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            if user.is_admin():
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        else:
            flash('Username atau password salah.', 'error')
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Anda telah berhasil logout.', 'info')
    return redirect(url_for('index'))

# --- Rute Publik & Pengguna ---
@app.route('/')
def index():
    query = {}
    search_performed = False
    origin = request.args.get('origin', '')
    destination = request.args.get('destination', '')
    departure_date = request.args.get('departure_date', '')

    if origin: query['origin'] = origin
    if destination: query['destination'] = destination
    if departure_date:
        search_performed = True
        try:
            start_date = datetime.strptime(departure_date, '%Y-%m-%d')
            end_date = start_date + timedelta(days=1)
            query['departure_time'] = {'$gte': start_date, '$lt': end_date}
        except ValueError:
            flash('Format tanggal tidak valid.', 'error')
            departure_date = '' # Reset jika error
            search_performed = False

    query['available_seats'] = {'$gt': 0}
    if 'departure_time' not in query:
        query['departure_time'] = {'$gte': datetime.now()}
    
    flights = list(flights_collection.find(query).sort('departure_time', 1))
    return render_template('index.html', flights=flights, search_performed=search_performed,
                           origin_filter=origin, destination_filter=destination, departure_date_filter=departure_date,
                           airports=get_unique_airports())

@app.route('/flight/<flight_id>')
def flight_details(flight_id):
    try:
        flight = flights_collection.find_one({'_id': ObjectId(flight_id)})
        if not flight:
            flash('Penerbangan tidak ditemukan.', 'error')
            return redirect(url_for('index'))
        return render_template('flight_details.html', flight=flight)
    except Exception:
        flash('ID Penerbangan tidak valid.', 'error')
        return redirect(url_for('index'))

@app.route('/book_flight/<flight_id>', methods=['POST'])
@login_required
def book_flight(flight_id):
    try:
        flight = flights_collection.find_one({'_id': ObjectId(flight_id)})
        if not flight:
            flash('Penerbangan tidak ditemukan.', 'error')
            return redirect(url_for('index'))
            
        num_passengers = int(request.form.get('num_passengers', 1))
        
        if flight['available_seats'] < num_passengers:
            flash('Maaf, jumlah kursi yang tersedia tidak mencukupi.', 'error')
            return redirect(url_for('flight_details', flight_id=flight_id))
        
        total_price = flight['price'] * num_passengers
        
        booking = {
            'user_id': ObjectId(current_user.id),
            'flight_id': ObjectId(flight_id),
            'num_passengers': num_passengers,
            'total_price': total_price,
            'booking_date': datetime.now(),
            'status': 'confirmed'
        }
        
        bookings_collection.insert_one(booking)
        flights_collection.update_one(
            {'_id': ObjectId(flight_id)},
            {'$inc': {'available_seats': -num_passengers}}
        )
        
        flash('Pemesanan tiket berhasil dikonfirmasi!', 'success')
        return redirect(url_for('my_bookings'))
    except Exception as e:
        flash(f'Terjadi kesalahan saat memesan tiket: {e}', 'error')
        return redirect(url_for('flight_details', flight_id=flight_id))

@app.route('/my_bookings')
@login_required
def my_bookings():
    try:
        pipeline = [
            {'$match': {'user_id': ObjectId(current_user.id)}},
            {'$lookup': {
                'from': 'flights',
                'localField': 'flight_id',
                'foreignField': '_id',
                'as': 'flight_details'
            }},
            {'$unwind': '$flight_details'},
            {'$sort': {'booking_date': -1}}
        ]
        user_bookings = list(bookings_collection.aggregate(pipeline))
        return render_template('my_bookings.html', bookings=user_bookings)
    except Exception as e:
        flash(f'Gagal memuat riwayat pemesanan: {e}', 'error')
        return render_template('my_bookings.html', bookings=[])


@app.route('/cancel_booking/<booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    try:
        booking = bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': ObjectId(current_user.id)})
        
        if not booking:
            flash('Pemesanan tidak ditemukan.', 'error')
            return redirect(url_for('my_bookings'))
            
        if booking['status'] == 'cancelled':
            flash('Pemesanan ini sudah pernah dibatalkan.', 'info')
            return redirect(url_for('my_bookings'))

        flights_collection.update_one(
            {'_id': booking['flight_id']},
            {'$inc': {'available_seats': booking['num_passengers']}}
        )
        bookings_collection.update_one(
            {'_id': ObjectId(booking_id)},
            {'$set': {'status': 'cancelled'}}
        )
        
        flash('Pemesanan berhasil dibatalkan.', 'success')
    except Exception as e:
        flash(f'Gagal membatalkan pesanan: {e}', 'error')

    return redirect(url_for('my_bookings'))

# --- Rute Khusus Admin ---
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    stats = {
        'total_users': users_collection.count_documents({}),
        'total_flights': flights_collection.count_documents({}),
        'total_bookings': bookings_collection.count_documents({'status': 'confirmed'})
    }
    return render_template('admin/admin_dashboard.html', stats=stats)

@app.route('/admin/users')
@login_required
@admin_required
def manage_users():
    users = list(users_collection.find().sort('created_at', -1))
    return render_template('admin/manage_users.html', users=users)

@app.route('/admin/users/delete/<user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        flash('Anda tidak dapat menghapus akun Anda sendiri.', 'error')
        return redirect(url_for('manage_users'))
    
    users_collection.delete_one({'_id': ObjectId(user_id)})
    flash('Pengguna berhasil dihapus.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/admin/flights')
@login_required
@admin_required
def manage_flights():
    flights = list(flights_collection.find().sort('departure_time', 1))
    return render_template('admin/manage_flights.html', flights=flights)

@app.route('/admin/flights/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_flight():
    if request.method == 'POST':
        try:
            total_seats = int(request.form['total_seats'])
            flight_data = {
                'flight_number': request.form['flight_number'].upper(),
                'origin': request.form['origin'].upper(),
                'destination': request.form['destination'].upper(),
                'departure_time': datetime.strptime(request.form['departure_time'], '%Y-%m-%dT%H:%M'),
                'arrival_time': datetime.strptime(request.form['arrival_time'], '%Y-%m-%dT%H:%M'),
                'price': float(request.form['price']),
                'total_seats': total_seats,
                'available_seats': total_seats
            }
            flights_collection.insert_one(flight_data)
            flash('Penerbangan berhasil ditambahkan!', 'success')
            return redirect(url_for('manage_flights'))
        except Exception as e:
            flash(f'Gagal menambahkan penerbangan: {e}', 'error')
    return render_template('admin/add_edit_flight.html', airports=get_unique_airports())

@app.route('/admin/flights/edit/<flight_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_flight(flight_id):
    try:
        flight = flights_collection.find_one({'_id': ObjectId(flight_id)})
        if not flight:
            flash('Penerbangan tidak ditemukan.', 'error')
            return redirect(url_for('manage_flights'))
            
        if request.method == 'POST':
            seats_occupied = flight['total_seats'] - flight['available_seats']
            new_total_seats = int(request.form['total_seats'])
            new_available_seats = new_total_seats - seats_occupied

            if new_available_seats < 0:
                flash('Total kursi baru tidak boleh kurang dari jumlah yang sudah dipesan.', 'error')
                return redirect(url_for('edit_flight', flight_id=flight_id))

            update_data = {
                '$set': {
                    'origin': request.form['origin'].upper(),
                    'destination': request.form['destination'].upper(),
                    'departure_time': datetime.strptime(request.form['departure_time'], '%Y-%m-%dT%H:%M'),
                    'arrival_time': datetime.strptime(request.form['arrival_time'], '%Y-%m-%dT%H:%M'),
                    'price': float(request.form['price']),
                    'total_seats': new_total_seats,
                    'available_seats': new_available_seats
                }
            }
            flights_collection.update_one({'_id': ObjectId(flight_id)}, update_data)
            flash('Penerbangan berhasil diperbarui!', 'success')
            return redirect(url_for('manage_flights'))
            
        return render_template('admin/add_edit_flight.html', flight_data=flight, airports=get_unique_airports())
    except Exception as e:
        flash(f'Terjadi kesalahan: {e}', 'error')
        return redirect(url_for('manage_flights'))

@app.route('/admin/flights/delete/<flight_id>', methods=['POST'])
@login_required
@admin_required
def delete_flight(flight_id):
    if bookings_collection.find_one({'flight_id': ObjectId(flight_id), 'status': 'confirmed'}):
        flash('Tidak bisa menghapus penerbangan yang memiliki pemesanan aktif.', 'error')
        return redirect(url_for('manage_flights'))
    
    flights_collection.delete_one({'_id': ObjectId(flight_id)})
    flash('Penerbangan berhasil dihapus.', 'success')
    return redirect(url_for('manage_flights'))

@app.route('/admin/bookings')
@login_required
@admin_required
def manage_all_bookings():
    try:
        pipeline = [
            {'$lookup': {
                'from': 'flights', 'localField': 'flight_id', 'foreignField': '_id', 'as': 'flight_details'
            }},
            {'$unwind': '$flight_details'},
            {'$lookup': {
                'from': 'users', 'localField': 'user_id', 'foreignField': '_id', 'as': 'user_details'
            }},
            {'$unwind': '$user_details'},
            {'$sort': {'booking_date': -1}}
        ]
        all_bookings = list(bookings_collection.aggregate(pipeline))
        return render_template('admin/manage_all_bookings.html', bookings=all_bookings)
    except Exception as e:
        flash(f'Gagal memuat data pemesanan: {e}', 'error')
        return render_template('admin/manage_all_bookings.html', bookings=[])

if __name__ == '__main__':
    app.run(debug=True)