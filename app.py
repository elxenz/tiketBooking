# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os

app = Flask(__name__)
# Penting: Ganti dengan secret key yang kuat dan unik!
# Idealnya, ambil dari variabel lingkungan saat deployment.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super_secret_key_for_ticket_booking_app_123!")

# --- Konfigurasi MongoDB ---
# Pastikan MongoDB Community Server berjalan di localhost:27017
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client['booking_tiket_db'] # Nama database Anda
users_collection = db['users']
flights_collection = db['flights']
bookings_collection = db['bookings']

# --- Konfigurasi Flask-Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Halaman yang akan dialihkan jika pengguna belum login

# Model Pengguna untuk Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']
        self.email = user_data['email']
        self.password_hash = user_data['password'] # Ini sudah di-hash

    # Metode yang diperlukan oleh UserMixin
    def get_id(self):
        return self.id

@login_manager.user_loader
def load_user(user_id):
    # Mengambil user dari database berdasarkan ID
    try:
        user_data = users_collection.find_one({'_id': ObjectId(user_id)})
        if user_data:
            return User(user_data)
    except Exception as e:
        print(f"Error loading user: {e}")
    return None

# --- Fungsi Pembantu ---
def get_unique_airports():
    """Mengambil daftar bandara asal dan tujuan unik dari koleksi penerbangan."""
    origins = flights_collection.distinct('origin')
    destinations = flights_collection.distinct('destination')
    # Gabungkan dan jadikan unik
    all_airports = sorted(list(set(origins + destinations)))
    return all_airports

def current_year():
    """Mengembalikan tahun saat ini."""
    return datetime.now().year

# --- Rute Autentikasi ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        flash('Anda sudah login.', 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if not all([username, email, password, confirm_password]):
            flash('Semua field wajib diisi!', 'error')
            return render_template('register.html')

        if password != confirm_password:
            flash('Konfirmasi password tidak cocok!', 'error')
            return render_template('register.html')

        if users_collection.find_one({'username': username}):
            flash('Username sudah digunakan!', 'error')
            return render_template('register.html')

        if users_collection.find_one({'email': email}):
            flash('Email sudah terdaftar!', 'error')
            return render_template('register.html')

        hashed_password = generate_password_hash(password)
        try:
            users_collection.insert_one({
                'username': username,
                'email': email,
                'password': hashed_password,
                'created_at': datetime.now()
            })
            flash('Registrasi berhasil! Silakan login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Terjadi kesalahan saat registrasi: {e}', 'error')
            return render_template('register.html')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        flash('Anda sudah login.', 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        user_data = users_collection.find_one({'username': username})

        if not user_data or not check_password_hash(user_data['password'], password):
            flash('Username atau password salah!', 'error')
            return render_template('login.html')

        user = User(user_data)
        login_user(user)
        flash(f'Selamat datang, {user.username}!', 'success')

        next_page = request.args.get('next')
        return redirect(next_page or url_for('index'))

    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    flash('Anda telah logout.', 'info')
    return redirect(url_for('index'))

# --- Rute Aplikasi Utama ---

@app.route('/', methods=['GET', 'POST'])
def index():
    airports = get_unique_airports()
    flights = []
    search_performed = False
    
    origin_filter = request.args.get('origin', '')
    destination_filter = request.args.get('destination', '')
    departure_date_filter = request.args.get('departure_date', '')

    query = {}
    if origin_filter:
        query['origin'] = origin_filter
    if destination_filter:
        query['destination'] = destination_filter
    
    if departure_date_filter:
        search_performed = True
        try:
            # Mengatur rentang tanggal dari awal hari hingga akhir hari
            start_of_day = datetime.strptime(departure_date_filter, '%Y-%m-%d')
            end_of_day = start_of_day + timedelta(days=1)
            query['departure_time'] = {'$gte': start_of_day, '$lt': end_of_day}
        except ValueError:
            flash('Format tanggal keberangkatan tidak valid.', 'error')
            return render_template(
                'index.html',
                airports=airports,
                flights=[],
                search_performed=False,
                origin_filter=origin_filter,
                destination_filter=destination_filter,
                departure_date_filter=departure_date_filter,
                current_year=current_year()
            )
            
    if request.method == 'POST': # Jika form pencarian disubmit via POST
        search_performed = True
        origin_filter = request.form.get('origin', '').strip()
        destination_filter = request.form.get('destination', '').strip()
        departure_date_filter = request.form.get('departure_date', '').strip()

        # Update query berdasarkan input form POST
        query = {}
        if origin_filter:
            query['origin'] = origin_filter
        if destination_filter:
            query['destination'] = destination_filter
        if departure_date_filter:
            try:
                start_of_day = datetime.strptime(departure_date_filter, '%Y-%m-%d')
                end_of_day = start_of_day + timedelta(days=1)
                query['departure_time'] = {'$gte': start_of_day, '$lt': end_of_day}
            except ValueError:
                flash('Format tanggal keberangkatan tidak valid.', 'error')
                # Reset search_performed jika ada error tanggal
                search_performed = False 
                
    try:
        # Hanya tampilkan penerbangan yang available_seats > 0
        query['available_seats'] = {'$gt': 0}
        
        # Urutkan berdasarkan waktu keberangkatan
        flights_cursor = flights_collection.find(query).sort('departure_time', 1)
        flights = []
        for flight in flights_cursor:
            flight['_id'] = str(flight['_id'])
            flights.append(flight)
    except Exception as e:
        flash(f'Terjadi kesalahan saat mencari penerbangan: {e}', 'error')
        flights = []
        search_performed = False

    return render_template(
        'index.html',
        airports=airports,
        flights=flights,
        search_performed=search_performed,
        origin_filter=origin_filter,
        destination_filter=destination_filter,
        departure_date_filter=departure_date_filter,
        current_year=current_year()
    )

@app.route('/flight/<flight_id>')
def flight_details(flight_id):
    try:
        flight = flights_collection.find_one({'_id': ObjectId(flight_id)})
        if not flight:
            flash('Penerbangan tidak ditemukan.', 'error')
            return redirect(url_for('index'))
        flight['_id'] = str(flight['_id']) # Konversi ObjectId ke string
        return render_template('flight_details.html', flight=flight, current_year=current_year())
    except Exception as e:
        flash(f'Terjadi kesalahan saat mengambil detail penerbangan: {e}', 'error')
        return redirect(url_for('index'))

@app.route('/book_flight/<flight_id>', methods=['POST'])
@login_required
def book_flight(flight_id):
    try:
        num_passengers = int(request.form.get('num_passengers', 1))

        if num_passengers <= 0:
            flash('Jumlah penumpang harus lebih dari 0.', 'error')
            return redirect(url_for('flight_details', flight_id=flight_id))

        flight = flights_collection.find_one({'_id': ObjectId(flight_id)})
        if not flight:
            flash('Penerbangan tidak ditemukan.', 'error')
            return redirect(url_for('index'))

        if flight['available_seats'] < num_passengers:
            flash('Jumlah kursi tidak cukup untuk pemesanan ini.', 'error')
            return redirect(url_for('flight_details', flight_id=flight_id))

        passengers_data = []
        for i in range(num_passengers):
            passenger_name = request.form.get(f'passenger_name_{i+1}', '').strip()
            passenger_dob_str = request.form.get(f'passenger_dob_{i+1}', '').strip()
            passenger_id_str = request.form.get(f'passenger_id_{i+1}', '').strip()

            if not all([passenger_name, passenger_dob_str, passenger_id_str]):
                flash('Mohon lengkapi semua data penumpang.', 'error')
                return redirect(url_for('flight_details', flight_id=flight_id))

            try:
                passenger_dob = datetime.strptime(passenger_dob_str, '%Y-%m-%d')
            except ValueError:
                flash('Format tanggal lahir penumpang tidak valid.', 'error')
                return redirect(url_for('flight_details', flight_id=flight_id))

            passengers_data.append({
                'name': passenger_name,
                'dob': passenger_dob,
                'id_number': passenger_id_str
            })

        total_price = flight['price'] * num_passengers

        booking_data = {
            'user_id': ObjectId(current_user.id),
            'flight_id': ObjectId(flight_id),
            'passengers': passengers_data,
            'num_passengers': num_passengers,
            'total_price': total_price,
            'booking_date': datetime.now(),
            'status': 'confirmed'
        }

        # Tanpa transaksi MongoDB
        flights_collection.update_one(
            {'_id': ObjectId(flight_id), 'available_seats': {'$gte': num_passengers}},
            {'$inc': {'available_seats': -num_passengers}}
        )
        bookings_collection.insert_one(booking_data)

        flash('Pemesanan berhasil dikonfirmasi!', 'success')
        return redirect(url_for('my_bookings'))

    except ValueError:
        flash('Jumlah penumpang tidak valid.', 'error')
        return redirect(url_for('flight_details', flight_id=flight_id))
    except Exception as e:
        flash(f'Terjadi kesalahan saat memproses pemesanan: {e}', 'error')
        return redirect(url_for('flight_details', flight_id=flight_id))


@app.route('/my_bookings')
@login_required # Hanya pengguna yang login yang bisa melihat riwayat
def my_bookings():
    user_id = ObjectId(current_user.id)
    try:
        # Menggunakan aggregation pipeline untuk mendapatkan detail penerbangan
        # yang terkait dengan setiap booking pengguna
        pipeline = [
            {'$match': {'user_id': user_id}},
            {'$lookup': {
                'from': 'flights',
                'localField': 'flight_id',
                'foreignField': '_id',
                'as': 'flight_details'
            }},
            {'$unwind': '$flight_details'}, # Deconstruct the array 'flight_details'
            {'$sort': {'booking_date': -1}} # Urutkan dari yang terbaru
        ]
        
        bookings_cursor = bookings_collection.aggregate(pipeline)
        bookings = []
        for booking in bookings_cursor:
            booking['_id'] = str(booking['_id'])
            # Konversi ObjectId dalam flight_details juga
            booking['flight_details']['_id'] = str(booking['flight_details']['_id'])
            bookings.append(booking)
            
    except Exception as e:
        flash(f'Terjadi kesalahan saat mengambil riwayat pemesanan: {e}', 'error')
        bookings = []

    return render_template('my_bookings.html', bookings=bookings, current_year=current_year())

@app.route('/cancel_booking/<booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    try:
        booking = bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': ObjectId(current_user.id)})
        if not booking:
            flash('Pemesanan tidak ditemukan atau Anda tidak memiliki izin untuk membatalkannya.', 'error')
            return redirect(url_for('my_bookings'))

        if booking['status'] == 'cancelled':
            flash('Pemesanan ini sudah dibatalkan.', 'info')
            return redirect(url_for('my_bookings'))

        flight_id = booking['flight_id']
        num_passengers = booking['num_passengers']

        # Tanpa transaksi MongoDB
        flights_collection.update_one(
            {'_id': flight_id},
            {'$inc': {'available_seats': num_passengers}}
        )
        bookings_collection.update_one(
            {'_id': ObjectId(booking_id)},
            {'$set': {'status': 'cancelled', 'cancellation_date': datetime.now()}}
        )

        flash('Pemesanan berhasil dibatalkan!', 'success')

    except Exception as e:
        flash(f'Terjadi kesalahan: {e}', 'error')

    return redirect(url_for('my_bookings'))

@app.route('/manage_flights')
@login_required # Hanya pengguna yang login yang bisa mengakses ini
def manage_flights():
    try:
        flights_cursor = flights_collection.find().sort('departure_time', 1)
        flights = []
        for flight in flights_cursor:
            flight['_id'] = str(flight['_id'])
            flights.append(flight)
    except Exception as e:
        flash(f'Terjadi kesalahan saat mengambil daftar penerbangan: {e}', 'error')
        flights = []
    
    return render_template('manage_flights.html', flights=flights, current_year=current_year())

@app.route('/add_flight', methods=['GET', 'POST'])
@login_required
def add_flight():
    airports = get_unique_airports() # Dapatkan daftar bandara unik yang ada
    
    if request.method == 'POST':
        flight_number = request.form['flight_number'].strip().upper()
        origin = request.form['origin'].strip().upper()
        destination = request.form['destination'].strip().upper()
        departure_time_str = request.form['departure_time'] # Format datetime-local
        arrival_time_str = request.form['arrival_time']
        price_str = request.form['price'].strip()
        total_seats_str = request.form['total_seats'].strip()

        if not all([flight_number, origin, destination, departure_time_str, arrival_time_str, price_str, total_seats_str]):
            flash('Semua field wajib diisi!', 'error')
            return render_template('add_edit_flight.html', airports=airports, current_year=current_year())

        try:
            departure_time = datetime.strptime(departure_time_str, '%Y-%m-%dT%H:%M')
            arrival_time = datetime.strptime(arrival_time_str, '%Y-%m-%dT%H:%M')
            price = float(price_str)
            total_seats = int(total_seats_str)

            if departure_time >= arrival_time:
                flash('Waktu keberangkatan harus sebelum waktu kedatangan.', 'error')
                return render_template('add_edit_flight.html', airports=airports, current_year=current_year(), 
                                       flight_data={'flight_number': flight_number, 'origin': origin, 
                                                    'destination': destination, 'price': price_str, 
                                                    'total_seats': total_seats_str})

            if price <= 0 or total_seats <= 0:
                flash('Harga dan jumlah kursi harus positif.', 'error')
                return render_template('add_edit_flight.html', airports=airports, current_year=current_year(), 
                                       flight_data={'flight_number': flight_number, 'origin': origin, 
                                                    'destination': destination, 'departure_time': departure_time_str,
                                                    'arrival_time': arrival_time_str, 'price': price_str, 
                                                    'total_seats': total_seats_str})
                                                    
            if flights_collection.find_one({'flight_number': flight_number}):
                flash('Nomor penerbangan sudah ada.', 'error')
                return render_template('add_edit_flight.html', airports=airports, current_year=current_year(), 
                                       flight_data={'flight_number': flight_number, 'origin': origin, 
                                                    'destination': destination, 'departure_time': departure_time_str,
                                                    'arrival_time': arrival_time_str, 'price': price_str, 
                                                    'total_seats': total_seats_str})

            flight_data = {
                'flight_number': flight_number,
                'origin': origin,
                'destination': destination,
                'departure_time': departure_time,
                'arrival_time': arrival_time,
                'price': price,
                'total_seats': total_seats,
                'available_seats': total_seats # Awalnya, semua kursi tersedia
            }
            flights_collection.insert_one(flight_data)
            flash('Penerbangan berhasil ditambahkan!', 'success')
            return redirect(url_for('manage_flights'))
        except ValueError:
            flash('Format harga atau jumlah kursi tidak valid.', 'error')
            return render_template('add_edit_flight.html', airports=airports, current_year=current_year(), 
                                   flight_data=request.form) # Kirimkan kembali data form yang sudah ada
        except Exception as e:
            flash(f'Terjadi kesalahan saat menambahkan penerbangan: {e}', 'error')
            return render_template('add_edit_flight.html', airports=airports, current_year=current_year(), 
                                   flight_data=request.form)

    return render_template('add_edit_flight.html', airports=airports, current_year=current_year())

@app.route('/edit_flight/<flight_id>', methods=['GET', 'POST'])
@login_required
def edit_flight(flight_id):
    airports = get_unique_airports()
    flight_to_edit = None
    try:
        flight_to_edit = flights_collection.find_one({'_id': ObjectId(flight_id)})
        if not flight_to_edit:
            flash('Penerbangan tidak ditemukan.', 'error')
            return redirect(url_for('manage_flights'))
        # Konversi ObjectId ke string dan datetime ke format input HTML
        flight_to_edit['_id'] = str(flight_to_edit['_id'])
        flight_to_edit['departure_time_str'] = flight_to_edit['departure_time'].strftime('%Y-%m-%dT%H:%M')
        flight_to_edit['arrival_time_str'] = flight_to_edit['arrival_time'].strftime('%Y-%m-%dT%H:%M')
    except Exception as e:
        flash(f'Terjadi kesalahan saat mengambil data penerbangan: {e}', 'error')
        return redirect(url_for('manage_flights'))

    if request.method == 'POST':
        flight_number = request.form['flight_number'].strip().upper()
        origin = request.form['origin'].strip().upper()
        destination = request.form['destination'].strip().upper()
        departure_time_str = request.form['departure_time']
        arrival_time_str = request.form['arrival_time']
        price_str = request.form['price'].strip()
        total_seats_str = request.form['total_seats'].strip()

        if not all([flight_number, origin, destination, departure_time_str, arrival_time_str, price_str, total_seats_str]):
            flash('Semua field wajib diisi!', 'error')
            return render_template('add_edit_flight.html', flight_data=flight_to_edit, airports=airports, current_year=current_year())

        try:
            departure_time = datetime.strptime(departure_time_str, '%Y-%m-%dT%H:%M')
            arrival_time = datetime.strptime(arrival_time_str, '%Y-%m-%dT%H:%M')
            price = float(price_str)
            total_seats = int(total_seats_str)

            if departure_time >= arrival_time:
                flash('Waktu keberangkatan harus sebelum waktu kedatangan.', 'error')
                return render_template('add_edit_flight.html', flight_data=request.form, airports=airports, current_year=current_year())

            if price <= 0 or total_seats <= 0:
                flash('Harga dan jumlah kursi harus positif.', 'error')
                return render_template('add_edit_flight.html', flight_data=request.form, airports=airports, current_year=current_year())
            
            # Periksa apakah nomor penerbangan sudah digunakan oleh penerbangan lain (kecuali penerbangan ini sendiri)
            existing_flight_num = flights_collection.find_one(
                {'flight_number': flight_number, '_id': {'$ne': ObjectId(flight_id)}}
            )
            if existing_flight_num:
                flash('Nomor penerbangan sudah ada untuk penerbangan lain.', 'error')
                return render_template('add_edit_flight.html', flight_data=request.form, airports=airports, current_year=current_year())

            # Hitung kembali available_seats: (total_seats_baru - (total_seats_lama - available_seats_lama))
            # Ini memastikan jumlah kursi yang sudah terisi tetap konsisten
            seats_occupied = flight_to_edit['total_seats'] - flight_to_edit['available_seats']
            new_available_seats = total_seats - seats_occupied
            
            if new_available_seats < 0:
                flash(f'Jumlah kursi total baru ({total_seats}) kurang dari jumlah kursi yang sudah terisi ({seats_occupied}).', 'error')
                return render_template('add_edit_flight.html', flight_data=request.form, airports=airports, current_year=current_year())


            updated_data = {
                'flight_number': flight_number,
                'origin': origin,
                'destination': destination,
                'departure_time': departure_time,
                'arrival_time': arrival_time,
                'price': price,
                'total_seats': total_seats,
                'available_seats': new_available_seats # Update available seats
            }
            flights_collection.update_one({'_id': ObjectId(flight_id)}, {'$set': updated_data})
            flash('Penerbangan berhasil diperbarui!', 'success')
            return redirect(url_for('manage_flights'))
        except ValueError:
            flash('Format data tidak valid.', 'error')
            return render_template('add_edit_flight.html', flight_data=request.form, airports=airports, current_year=current_year())
        except Exception as e:
            flash(f'Terjadi kesalahan saat memperbarui penerbangan: {e}', 'error')
            return render_template('add_edit_flight.html', flight_data=request.form, airports=airports, current_year=current_year())
    
    return render_template('add_edit_flight.html', flight_data=flight_to_edit, airports=airports, current_year=current_year())


@app.route('/delete_flight/<flight_id>', methods=['POST'])
@login_required
def delete_flight(flight_id):
    try:
        # Sebelum menghapus penerbangan, periksa apakah ada booking yang terkait
        if bookings_collection.find_one({'flight_id': ObjectId(flight_id), 'status': 'confirmed'}):
            flash('Tidak bisa menghapus penerbangan. Ada pemesanan yang dikonfirmasi terkait penerbangan ini.', 'error')
        else:
            result = flights_collection.delete_one({'_id': ObjectId(flight_id)})
            if result.deleted_count > 0:
                # Hapus juga booking yang berstatus 'cancelled' atau 'pending' terkait penerbangan ini
                bookings_collection.delete_many({'flight_id': ObjectId(flight_id)})
                flash('Penerbangan berhasil dihapus!', 'success')
            else:
                flash('Penerbangan tidak ditemukan atau gagal dihapus.', 'error')
    except Exception as e:
        flash(f'Terjadi kesalahan saat menghapus penerbangan: {e}', 'error')
    
    return redirect(url_for('manage_flights'))

# --- Jalankan Aplikasi ---
if __name__ == '__main__':
    # Untuk menjalankan transaksi MongoDB, Anda memerlukan MongoDB replica set.
    # Jika Anda menjalankan MongoDB secara lokal sebagai instance standalone,
    # fungsi transaksi mungkin tidak bekerja. Anda bisa menghapus start_transaction(),
    # commit_transaction(), abort_transaction(), dan end_session() jika tidak menggunakan replica set,
    # tetapi perhatikan bahwa ini akan menghilangkan jaminan atomisitas.
    # Contoh data dummy untuk memulai
    if users_collection.count_documents({}) == 0:
        print("Menambahkan user dummy...")
        users_collection.insert_one({
            'username': 'user',
            'email': 'user@example.com',
            'password': generate_password_hash('password'),
            'created_at': datetime.now()
        })
        users_collection.insert_one({
            'username': 'admin',
            'email': 'admin@example.com',
            'password': generate_password_hash('adminpass'),
            'created_at': datetime.now()
        })
    
    if flights_collection.count_documents({}) == 0:
        print("Menambahkan penerbangan dummy...")
        flights_collection.insert_many([
            {
                'flight_number': 'GA100', 'origin': 'CGK', 'destination': 'DPS',
                'departure_time': datetime(2025, 7, 10, 8, 0),
                'arrival_time': datetime(2025, 7, 10, 10, 0),
                'price': 1500000.0, 'total_seats': 100, 'available_seats': 100
            },
            {
                'flight_number': 'JT200', 'origin': 'DPS', 'destination': 'SUB',
                'departure_time': datetime(2025, 7, 11, 14, 30),
                'arrival_time': datetime(2025, 7, 11, 15, 30),
                'price': 800000.0, 'total_seats': 80, 'available_seats': 80
            },
            {
                'flight_number': 'QG300', 'origin': 'CGK', 'destination': 'SUB',
                'departure_time': datetime(2025, 7, 12, 9, 0),
                'arrival_time': datetime(2025, 7, 12, 10, 30),
                'price': 1000000.0, 'total_seats': 120, 'available_seats': 120
            },
            {
                'flight_number': 'ID400', 'origin': 'DPS', 'destination': 'CGK',
                'departure_time': datetime(2025, 7, 13, 17, 0),
                'arrival_time': datetime(2025, 7, 13, 19, 0),
                'price': 1600000.0, 'total_seats': 90, 'available_seats': 90
            },
            {
                'flight_number': 'SJ500', 'origin': 'SUB', 'destination': 'CGK',
                'departure_time': datetime(2025, 7, 14, 7, 0),
                'arrival_time': datetime(2025, 7, 14, 8, 30),
                'price': 950000.0, 'total_seats': 70, 'available_seats': 70
            }
        ])

    app.run(debug=True) # debug=True hanya untuk pengembangan
