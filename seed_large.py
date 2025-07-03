# seed_large.py
import random
from pymongo import MongoClient
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
from faker import Faker

# Inisialisasi Faker untuk data Indonesia
fake = Faker('id_ID')

# --- Konfigurasi ---
MONGO_URI = "mongodb://localhost:27017/"
client = MongoClient(MONGO_URI)
db = client['booking_tiket_db']

def seed_data():
    """Fungsi utama untuk mengisi database dengan data dummy dalam jumlah besar."""
    
    # --- 1. Hapus Data Lama ---
    print("Mulai proses seeding...")
    try:
        db.users.delete_many({})
        db.flights.delete_many({})
        db.bookings.delete_many({})
        print("✔️ Data lama berhasil dihapus.")
    except Exception as e:
        print(f"❌ Error saat menghapus data: {e}")
        return

    # --- 2. Generate Data Pengguna (100 pengguna) ---
    print("👤 Membuat 100 data pengguna...")
    users = []
    # Admin pertama
    admin_user = {
        "username": "admin", "email": "admin@tiketku.com",
        "password": generate_password_hash("admin123"), "role": "admin",
        "created_at": fake.past_datetime() # <-- DIPERBAIKI
    }
    users.append(admin_user)

    # 99 pengguna biasa
    for _ in range(99):
        profile = fake.simple_profile()
        users.append({
            "username": profile['username'], "email": profile['mail'],
            "password": generate_password_hash("user123"), "role": "user",
            "created_at": fake.past_datetime() # <-- DIPERBAIKI
        })
    
    try:
        user_ids = db.users.insert_many(users).inserted_ids
        print(f"✔️ Berhasil menambahkan {len(user_ids)} pengguna.")
    except Exception as e:
        print(f"❌ Error saat menambahkan pengguna: {e}")
        return

    # --- 3. Generate Data Penerbangan (150 penerbangan) ---
    print("✈️ Membuat 150 data penerbangan...")
    airports = ['CGK', 'DPS', 'SUB', 'UPG', 'KNO', 'BPN', 'JOG', 'PLM', 'BTH', 'MDC']
    airlines = ['GA', 'JT', 'QG', 'ID', 'SJ', 'IW']
    flights = []

    for _ in range(150):
        origin, destination = random.sample(airports, 2)
        departure = fake.date_time_between(start_date='-30d', end_date='+90d')
        duration = timedelta(hours=random.randint(1, 5), minutes=random.choice([0, 15, 30, 45]))
        arrival = departure + duration
        total_seats = random.choice([100, 120, 150, 180])

        flights.append({
            'flight_number': f"{random.choice(airlines)}{random.randint(100, 999)}",
            'origin': origin, 'destination': destination,
            'departure_time': departure, 'arrival_time': arrival,
            'price': float(random.randrange(500, 3000) * 1000),
            'total_seats': total_seats, 'available_seats': total_seats
        })
    
    try:
        flight_ids = db.flights.insert_many(flights).inserted_ids
        print(f"✔️ Berhasil menambahkan {len(flight_ids)} penerbangan.")
    except Exception as e:
        print(f"❌ Error saat menambahkan penerbangan: {e}")
        return
        
    # --- 4. Generate Data Pemesanan (300 pemesanan) ---
    print("🎟️  Membuat 300 data pemesanan...")
    bookings = []
    
    all_user_ids = [doc['_id'] for doc in db.users.find({}, {'_id': 1})]
    all_flight_ids = [doc['_id'] for doc in db.flights.find({}, {'_id': 1})]

    if not all_user_ids or not all_flight_ids:
        print("❌ Tidak ada pengguna atau penerbangan untuk dibuatkan booking. Proses dihentikan.")
        return

    for _ in range(300):
        flight_id = random.choice(all_flight_ids)
        flight = db.flights.find_one({'_id': flight_id})
        
        if not flight:
            continue

        num_passengers = random.randint(1, 4)

        if flight['available_seats'] >= num_passengers:
            bookings.append({
                'user_id': random.choice(all_user_ids),
                'flight_id': flight_id,
                'num_passengers': num_passengers,
                'total_price': flight['price'] * num_passengers,
                'booking_date': fake.date_time_between(start_date='-60d', end_date='-1d'),
                'status': random.choice(['confirmed', 'confirmed', 'confirmed', 'cancelled'])
            })
            
            db.flights.update_one(
                {'_id': flight_id},
                {'$inc': {'available_seats': -num_passengers}}
            )

    if bookings:
        try:
            booking_ids = db.bookings.insert_many(bookings).inserted_ids
            print(f"✔️ Berhasil menambahkan {len(booking_ids)} pemesanan.")
        except Exception as e:
            print(f"❌ Error saat menambahkan pemesanan: {e}")

    print("\n✅ Proses Seeding Selesai!")
    client.close()

if __name__ == '__main__':
    seed_data()