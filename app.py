import os
import sqlite3
import qrcode
import io
import base64
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename

# --- App Initialization ---
app = Flask(__name__)
app.secret_key = "ultimate_lms_premium_key"

# --- Folders Setup ---
UPLOAD_FOLDER = 'static/uploads/'
VIDEO_FOLDER = 'static/uploads/videos/'
NOTES_FOLDER = 'static/uploads/notes/'
# Folder for your manual QR code
QR_FOLDER = 'static/uploads/qrcodes/' 

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx'}

app.config.update(
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    VIDEO_FOLDER=VIDEO_FOLDER,
    NOTES_FOLDER=NOTES_FOLDER,
    QR_FOLDER=QR_FOLDER,
    MAX_CONTENT_LENGTH=500 * 1024 * 1024 
)

# Ensure all directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VIDEO_FOLDER, exist_ok=True)
os.makedirs(NOTES_FOLDER, exist_ok=True)
os.makedirs(QR_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Database Helpers ---
def get_db_connection():
    # Changed to database.db to match your init_db function
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT UNIQUE, password TEXT, mobile TEXT, college TEXT, address TEXT, photo TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS courses (id INTEGER PRIMARY KEY AUTOINCREMENT, course_name TEXT, description TEXT, price REAL DEFAULT 0.0, qr_code TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER, title TEXT, file_path TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, course_id INTEGER, title TEXT, file_path TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS enrollments (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER, course_id INTEGER, amount REAL, status TEXT DEFAULT "pending")')
    conn.execute('CREATE TABLE IF NOT EXISTS admin (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)')
    
    if not conn.execute("SELECT * FROM admin WHERE username='admin'").fetchone():
        conn.execute("INSERT INTO admin (username, password) VALUES ('admin', 'admin123')")
    conn.commit()
    conn.close()

def query_db(query, args=(), one=False):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(query, args)
    rv = cur.fetchall()
    conn.commit()
    conn.close()
    return (rv[0] if rv else None) if one else rv

# --- Payment Helper (Dynamic QR Generation) ---
def generate_upi_qr(upi_id, name, amount):
    upi_url = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

# --- GENERAL ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for('index'))

# --- STUDENT ROUTES ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            query_db("INSERT INTO students (name, email, password, photo) VALUES (?, ?, ?, ?)", 
                     (request.form['name'], request.form['email'], request.form['password'], 'default.png'))
            flash("Registration Successful! Please Login.", "success")
            return redirect(url_for('login'))
        except: 
            flash("Email already registered.", "danger")
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = query_db("SELECT * FROM students WHERE email=? AND password=?", (request.form['email'], request.form['password']), one=True)
        if user:
            session.update(user_id=user['id'], user_name=user['name'], role='student')
            return redirect(url_for('student_dashboard'))
        flash("Invalid Credentials", "danger")
    return render_template('login.html')

@app.route('/student_dashboard')
def student_dashboard():
    if session.get('role') != 'student': return redirect(url_for('login'))
    courses = query_db("SELECT * FROM courses")
    
    # Get list of course IDs student has already paid for
    enrolled_data = query_db("SELECT course_id FROM enrollments WHERE student_id=? AND status='completed'", (session['user_id'],))
    enrolled_list = [r['course_id'] for r in enrolled_data]
    
    return render_template('student_dashboard.html', courses=courses, enrolled_list=enrolled_list)

# --- ADMIN ROUTES ---

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        admin = query_db("SELECT * FROM admin WHERE username=? AND password=?", (request.form['username'], request.form['password']), one=True)
        if admin:
            session.update(admin_id=admin['id'], role='admin')
            return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')

@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    courses = query_db("SELECT * FROM courses")
    students = query_db("SELECT * FROM students")
    enrolls = query_db("SELECT students.name, courses.course_name, enrollments.amount FROM enrollments JOIN students ON enrollments.student_id = students.id JOIN courses ON enrollments.course_id = courses.id")
    return render_template('admin_dashboard.html', courses=courses, students=students, enrollments=enrolls)

@app.route('/add_course', methods=['POST'])
def add_course():
    if session.get('role') == 'admin':
        query_db("INSERT INTO courses (course_name, description, price) VALUES (?, ?, ?)", 
                 (request.form['course_name'], request.form['description'], request.form['price']))
        flash("Course added successfully!", "success")
    return redirect(url_for('admin_dashboard'))

# --- PAYMENT & ENROLLMENT ---

@app.route('/checkout/<int:course_id>')
def checkout(course_id):
    if session.get('role') != 'student': return redirect(url_for('login'))
    course = query_db("SELECT * FROM courses WHERE id=?", (course_id,), one=True)
    
    # You can either use the generated QR code:
    qr_img = generate_upi_qr("yourname@upi", "EduStream", course['price'])
    
    # OR if you want to use your manual 'my_qr.jpeg', 
    # the HTML will look for it in static/uploads/qrcodes/my_qr.jpeg
    return render_template('checkout.html', course=course, qr_code=qr_img)

@app.route('/process_payment/<int:course_id>', methods=['POST'])
def process_payment(course_id):
    if session.get('role') != 'student': 
        return redirect(url_for('login'))
    
    course = query_db("SELECT * FROM courses WHERE id=?", (course_id,), one=True)
    
    if course:
        # Save to enrollments table using correct column names from init_db
        query_db("INSERT INTO enrollments (student_id, course_id, amount, status) VALUES (?, ?, ?, 'completed')", 
                 (session['user_id'], course_id, course['price']))
        flash(f"Payment Successful! You are now enrolled in {course['course_name']}", "success")
    
    return redirect(url_for('student_dashboard'))

# --- WATCH CONTENT ---

@app.route('/watch_course/<int:course_id>')
def watch_course(course_id):
    if session.get('role') != 'student': return redirect(url_for('login'))
    
    # Security: Check if student is actually enrolled before letting them watch
    check = query_db("SELECT * FROM enrollments WHERE student_id=? AND course_id=? AND status='completed'", 
                     (session['user_id'], course_id), one=True)
    if not check:
        flash("Please purchase the course to view content.", "warning")
        return redirect(url_for('student_dashboard'))

    course = query_db("SELECT * FROM courses WHERE id=?", (course_id,), one=True)
    videos = query_db("SELECT * FROM videos WHERE course_id=?", (course_id,))
    notes = query_db("SELECT * FROM notes WHERE course_id=?", (course_id,))
    
    v_id = request.args.get('video_id', type=int)
    sel = query_db("SELECT * FROM videos WHERE id=?", (v_id,), one=True) if v_id else (videos[0] if videos else None)
    
    return render_template('course_content.html', course=course, videos=videos, notes=notes, selected_video=sel)


# --- MISSING PROFILE ROUTES ---

@app.route('/profile')
def profile():
    if session.get('role') != 'student': 
        return redirect(url_for('login'))
    
    # Fetch the logged-in student's data
    student = query_db("SELECT * FROM students WHERE id=?", (session['user_id'],), one=True)
    return render_template('student_profile.html', student=student)

@app.route('/edit_profile', methods=['POST'])
def edit_profile():
    if session.get('role') != 'student': 
        return redirect(url_for('login'))
        
    # Update student details
    query_db("UPDATE students SET name=?, mobile=?, college=?, address=? WHERE id=?", 
             (request.form['name'], request.form['mobile'], request.form['college'], 
              request.form['address'], session['user_id']))
    
    flash("Profile updated successfully!", "success")
    return redirect(url_for('profile'))

@app.route('/upload_photo', methods=['POST'])
def upload_photo():
    if session.get('role') != 'student': 
        return redirect(url_for('login'))
        
    file = request.files.get('photo')
    if file and allowed_file(file.filename):
        filename = secure_filename(f"user_{session['user_id']}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        query_db("UPDATE students SET photo=? WHERE id=?", (filename, session['user_id']))
        flash("Photo updated!", "success")
    else:
        flash("Invalid file format.", "danger")
    return redirect(url_for('profile'))


# --- MISSING ADMIN CONTENT ROUTES ---

@app.route('/upload_video/<int:course_id>', methods=['POST'])
def upload_video(course_id):
    if session.get('role') == 'admin':
        v_file = request.files.get('video_file')
        if v_file:
            v_name = secure_filename(v_file.filename)
            # Ensure the directory exists
            os.makedirs(app.config['VIDEO_FOLDER'], exist_ok=True)
            v_file.save(os.path.join(app.config['VIDEO_FOLDER'], v_name))
            
            query_db("INSERT INTO videos (course_id, title, file_path) VALUES (?, ?, ?)", 
                     (course_id, request.form['video_title'], v_name))
            flash("Video uploaded successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/upload_note/<int:course_id>', methods=['POST'])
def upload_note(course_id):
    if session.get('role') == 'admin':
        n_file = request.files.get('note_file')
        if n_file:
            n_name = secure_filename(n_file.filename)
            # Ensure the directory exists
            os.makedirs(app.config['NOTES_FOLDER'], exist_ok=True)
            n_file.save(os.path.join(app.config['NOTES_FOLDER'], n_name))
            
            query_db("INSERT INTO notes (course_id, title, file_path) VALUES (?, ?, ?)", 
                     (course_id, request.form['note_title'], n_name))
            flash("Note uploaded successfully!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_course/<int:id>')
def delete_course(id):
    if session.get('role') == 'admin':
        query_db("DELETE FROM courses WHERE id=?", (id,))
        flash("Course deleted successfully.", "info")
    return redirect(url_for('admin_dashboard'))
if __name__ == '__main__':
    init_db()
    app.run(debug=True)