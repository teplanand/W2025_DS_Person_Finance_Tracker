# app.py
from collections import defaultdict
import pickle
from flask import Flask, request, jsonify, session, redirect, url_for, render_template
from flask_sqlalchemy import SQLAlchemy
import numpy as np
from sklearn.linear_model import LinearRegression
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import calendar
from sqlalchemy import func, extract

app = Flask(__name__)
# SQLite for simplicity
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///finance_tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.urandom(24)  # For session management
db = SQLAlchemy(app)

# Models


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    monthly_income = db.Column(db.Float, default=0.0)
    transactions = db.relationship('Transaction', backref='user', lazy=True)
    monthly_summaries = db.relationship(
        'MonthlySummary', backref='user', lazy=True)


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)

    # New field to track additional savings (separate from calculated savings)
    is_saving = db.Column(db.Boolean, default=False)

    CATEGORIES = [
        'Shopping',
        'Healthcare',
        'Rent',
        'Transport',
        'Utilities',
        'Food',
        'Savings',
        'Other'
    ]


class MonthlySummary(db.Model):
    __tablename__ = 'monthly_summaries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    income = db.Column(db.Float, default=0.0)
    expenses = db.Column(db.Float, default=0.0)
    savings = db.Column(db.Float, default=0.0)

    # Define a unique constraint for user, month, and year
    __table_args__ = (db.UniqueConstraint('user_id', 'month', 'year'),)


class CategorySummary(db.Model):
    __tablename__ = 'category_summaries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, default=0.0)
    # 'increasing', 'decreasing', 'stable'
    trend = db.Column(db.String(20), default='stable')

    # Define a unique constraint for user, category, month, and year
    __table_args__ = (db.UniqueConstraint(
        'user_id', 'category', 'month', 'year'),)

# Root route - redirect to login or dashboard based on session


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard_page'))
    else:
        return redirect(url_for('login'))

# Route for user registration page (GET) and registration process (POST)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return render_template('register.html', error="Email already exists. Please use a different email.")
        
        try:
            user = User(name=name, email=email, password_hash=password)
            db.session.add(user)
            db.session.commit()
            return redirect(url_for('login'))
        except Exception as e:
            return f"Error: {str(e)}"

    return render_template('register.html')
# Route for user login page (GET) and login process (POST)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('dashboard_page'))
        elif user:
            return render_template('login.html', error="Invalid password")
        else:
            return render_template('login.html', error="User not found")

    return render_template('login.html')

# Dashboard page route (HTML)


@app.route('/dashboard_page')
def dashboard_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Get categories for the dropdown
    categories = Transaction.CATEGORIES

    # Just render the template - data will be loaded via AJAX
    return render_template('dashboard.html', categories=categories)

# Dashboard API route (JSON)


@app.route('/dashboard_data')
def dashboard_data():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"})

    user_id = session['user_id']
    user = User.query.filter_by(id=user_id).first()

    if not user:
        return jsonify({"error": "User not found"})

    # Get current month and year
    today = datetime.today()
    current_month = today.month
    current_year = today.year

    # Get monthly summary for current month
    monthly_summary = MonthlySummary.query.filter_by(
        user_id=user_id,
        month=current_month,
        year=current_year
    ).first()

    if not monthly_summary:
        monthly_summary = {
            "income": user.monthly_income,
            "expenses": 0,
            "savings": 0
        }
    else:
        monthly_summary = {
            "income": monthly_summary.income,
            "expenses": monthly_summary.expenses,
            "savings": monthly_summary.savings
        }

    # Get recent transactions
    transactions = Transaction.query.filter_by(
        user_id=user_id
    ).order_by(Transaction.date.desc()).limit(5).all()

    transactions_list = []
    for transaction in transactions:
        transactions_list.append({
            "id": transaction.id,
            "amount": transaction.amount,
            "category": transaction.category,
            "date": transaction.date.strftime('%Y-%m-%d %H:%M:%S'),
            "is_saving": transaction.is_saving
        })

    # Get category summaries for current month
    category_summaries = CategorySummary.query.filter_by(
        user_id=user_id,
        month=current_month,
        year=current_year
    ).all()

    category_data = []
    for summary in category_summaries:
        category_data.append({
            "category": summary.category,
            "amount": summary.amount,
            "trend": summary.trend
        })

    return jsonify({
        "user": {
            "name": user.name,
            "email": user.email,
            "monthly_income": user.monthly_income
        },
        "monthly_summary": monthly_summary,
        "transactions": transactions_list,
        "category_summaries": category_data
    })

# Update monthly income


@app.route('/update_income', methods=['POST'])
def update_income():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Unauthorized access"})

    user_id = session['user_id']
    user = User.query.get(user_id)

    if not user:
        return jsonify({"success": False, "message": "User not found"})

    try:
        monthly_income = float(request.form['monthly_income'])
        user.monthly_income = monthly_income

        # Update or create monthly summary for current month
        today = datetime.today()
        current_month = today.month
        current_year = today.year

        monthly_summary = MonthlySummary.query.filter_by(
            user_id=user_id,
            month=current_month,
            year=current_year
        ).first()

        if monthly_summary:
            monthly_summary.income = monthly_income
            # Recalculate savings
            monthly_summary.savings = monthly_income - monthly_summary.expenses
        else:
            monthly_summary = MonthlySummary(
                user_id=user_id,
                month=current_month,
                year=current_year,
                income=monthly_income,
                expenses=0,
                savings=monthly_income
            )
            db.session.add(monthly_summary)

        db.session.commit()
        return jsonify({"success": True, "message": "Income updated successfully!"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Unauthorized access"})

    user_id = session['user_id']
    user = User.query.get(user_id)

    if not user:
        return jsonify({"success": False, "message": "User not found"})

    try:
        amount = float(request.form['amount'])
        category = request.form['category']
        is_saving = request.form.get('is_saving', 'false').lower() == 'true'

        # Get the transaction date if provided, otherwise use today
        transaction_date = None
        if 'transaction_date' in request.form and request.form['transaction_date']:
            # Convert the date string to a datetime object
            date_str = request.form['transaction_date']
            transaction_date = datetime.strptime(date_str, '%Y-%m-%d')
        else:
            transaction_date = datetime.today()

        # Make amount negative for expenses
        if category != 'Savings' and not is_saving and amount > 0:
            amount = -amount

        transaction = Transaction(
            user_id=user_id,
            amount=amount,
            category=category,
            is_saving=is_saving,
            date=transaction_date  # Use the provided or default date
        )
        db.session.add(transaction)

        # Update monthly summary - use the month and year from the transaction date
        month = transaction_date.month
        year = transaction_date.year

        # Get or create monthly summary
        monthly_summary = MonthlySummary.query.filter_by(
            user_id=user_id,
            month=month,
            year=year
        ).first()

        if not monthly_summary:
            monthly_summary = MonthlySummary(
                user_id=user_id,
                month=month,
                year=year,
                income=user.monthly_income,
                expenses=0,
                savings=0
            )
            db.session.add(monthly_summary)

        # Update expenses or savings
        if category == 'Savings' or is_saving:
            monthly_summary.savings += amount
        else:
            monthly_summary.expenses += abs(amount)

        # Recalculate total savings
        monthly_summary.savings = monthly_summary.income - monthly_summary.expenses

        # Update or create category summary
        category_summary = CategorySummary.query.filter_by(
            user_id=user_id,
            category=category,
            month=month,
            year=year
        ).first()

        if category_summary:
            # Get the most recent transaction for this category
            prev_transaction = Transaction.query.filter_by(
                user_id=user_id,
                category=category
            ).filter(
                Transaction.id != transaction.id  # Exclude current transaction
            ).order_by(Transaction.date.desc()).first()

            # Compare current transaction amount with previous transaction amount
            if prev_transaction:
                current_abs_amount = abs(amount)
                prev_abs_amount = abs(prev_transaction.amount)

                if current_abs_amount > prev_abs_amount:
                    category_summary.trend = 'increasing'
                elif current_abs_amount < prev_abs_amount:
                    category_summary.trend = 'decreasing'
                else:
                    category_summary.trend = 'stable'

            # Update the total amount
            category_summary.amount += abs(amount)
        else:
            # Check previous month for trend comparison
            prev_month = month - 1
            prev_year = year
            if prev_month == 0:
                prev_month = 12
                prev_year -= 1

            # Look for the most recent transaction in this category
            prev_transaction = Transaction.query.filter_by(
                user_id=user_id,
                category=category
            ).filter(
                Transaction.id != transaction.id  # Exclude current transaction
            ).order_by(Transaction.date.desc()).first()

            trend = 'stable'
            if prev_transaction:
                current_abs_amount = abs(amount)
                prev_abs_amount = abs(prev_transaction.amount)

                if current_abs_amount > prev_abs_amount:
                    trend = 'increasing'
                elif current_abs_amount < prev_abs_amount:
                    trend = 'decreasing'

            category_summary = CategorySummary(
                user_id=user_id,
                category=category,
                month=month,
                year=year,
                amount=abs(amount),
                trend=trend
            )
            db.session.add(category_summary)

        db.session.commit()
        return jsonify({"success": True, "message": "Transaction added!"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


# Route for fetching all transactions with monthly filtering
@app.route('/fetch_all_transactions')
def fetch_all_transactions():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"})

    user_id = session['user_id']

    # Optional filter parameters
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)

    # Base query
    query = Transaction.query.filter_by(user_id=user_id)

    # Apply filters if provided
    if month and year:
        query = query.filter(
            extract('month', Transaction.date) == month,
            extract('year', Transaction.date) == year
        )

    transactions = query.order_by(Transaction.date.desc()).all()

    transactions_list = []
    for transaction in transactions:
        transactions_list.append({
            "id": transaction.id,
            "amount": transaction.amount,
            "category": transaction.category,
            "date": transaction.date.strftime('%Y-%m-%d %H:%M:%S'),
            "is_saving": transaction.is_saving
        })

    return jsonify(transactions_list)

# Route for fetching recent transactions (limit 5)


@app.route('/fetch_transactions')
def fetch_transactions():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"})

    user_id = session['user_id']
    transactions = Transaction.query.filter_by(
        user_id=user_id
    ).order_by(Transaction.date.desc()).limit(5).all()

    transactions_list = []
    for transaction in transactions:
        transactions_list.append({
            "id": transaction.id,
            "amount": transaction.amount,
            "category": transaction.category,
            "date": transaction.date.strftime('%Y-%m-%d %H:%M:%S'),
            "is_saving": transaction.is_saving
        })

    return jsonify(transactions_list)

# Route for fetching monthly summary


@app.route('/fetch_monthly_summary')
def fetch_monthly_summary():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"})

    user_id = session['user_id']

    # Get month and year from request, default to current month/year
    month = request.args.get('month', datetime.today().month, type=int)
    year = request.args.get('year', datetime.today().year, type=int)

    # Get monthly summary
    monthly_summary = MonthlySummary.query.filter_by(
        user_id=user_id,
        month=month,
        year=year
    ).first()

    # Get user for monthly income
    user = User.query.get(user_id)

    if not monthly_summary:
        # If no summary exists, create a default response with current monthly income
        return jsonify({
            "income": user.monthly_income if user else 0,
            "expenses": 0,
            "savings": user.monthly_income if user else 0,
            "month": month,
            "year": year
        })

    return jsonify({
        "income": monthly_summary.income,
        "expenses": monthly_summary.expenses,
        "savings": monthly_summary.savings,
        "month": month,
        "year": year
    })

# Route for fetching category trends


@app.route('/fetch_category_trends')
def fetch_category_trends():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"})

    user_id = session['user_id']

    # Get month and year from request, default to current month/year
    month = request.args.get('month', datetime.today().month, type=int)
    year = request.args.get('year', datetime.today().year, type=int)

    # Get category summaries
    category_summaries = CategorySummary.query.filter_by(
        user_id=user_id,
        month=month,
        year=year
    ).all()

    categories_data = []
    for summary in category_summaries:
        categories_data.append({
            "category": summary.category,
            "amount": summary.amount,
            "trend": summary.trend
        })

    return jsonify(categories_data)


@app.route('/edit_transaction', methods=['POST'])
def edit_transaction():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "User not logged in"})

    user_id = session['user_id']
    data = request.get_json()

    transaction_id = data['id']
    category = data['category']
    amount = data['amount']
    is_saving = data.get('is_saving', False)

    # Handle transaction date if provided
    transaction_date = None
    if 'transaction_date' in data and data['transaction_date']:
        try:
            transaction_date = datetime.strptime(
                data['transaction_date'], '%Y-%m-%d')
        except ValueError:
            return jsonify({"success": False, "message": "Invalid date format. Please use YYYY-MM-DD."})

    # Get the transaction
    transaction = Transaction.query.filter_by(
        id=transaction_id, user_id=user_id
    ).first()

    if not transaction:
        return jsonify({"success": False, "message": "Transaction not found"})

    try:
        # Get old transaction details to update monthly summary
        old_amount = transaction.amount
        old_category = transaction.category
        old_is_saving = transaction.is_saving
        old_date = transaction.date
        old_month = old_date.month
        old_year = old_date.year

        # Make amount negative for expenses (if needed)
        if category != 'Savings' and not is_saving and amount > 0:
            amount = -amount

        # Update transaction
        transaction.amount = amount
        transaction.category = category
        transaction.is_saving = is_saving

        # Update date if provided
        if transaction_date:
            transaction.date = transaction_date

        # Get new date information
        new_date = transaction.date
        new_month = new_date.month
        new_year = new_date.year

        # If month or year changed, need to update both old and new monthly summaries
        if old_month != new_month or old_year != new_year:
            # Update old monthly summary (remove the transaction)
            old_monthly_summary = MonthlySummary.query.filter_by(
                user_id=user_id,
                month=old_month,
                year=old_year
            ).first()

            if old_monthly_summary:
                # Reverse old transaction impact
                if old_category == 'Savings' or old_is_saving:
                    old_monthly_summary.savings -= old_amount
                else:
                    old_monthly_summary.expenses -= abs(old_amount)

                # Recalculate total savings for old month
                old_monthly_summary.savings = old_monthly_summary.income - \
                    old_monthly_summary.expenses

            # Update or create new monthly summary
            new_monthly_summary = MonthlySummary.query.filter_by(
                user_id=user_id,
                month=new_month,
                year=new_year
            ).first()

            if not new_monthly_summary:
                new_monthly_summary = MonthlySummary(
                    user_id=user_id,
                    month=new_month,
                    year=new_year,
                    income=User.query.get(user_id).monthly_income,
                    expenses=0,
                    savings=0
                )
                db.session.add(new_monthly_summary)

            # Apply new transaction impact to new month
            if category == 'Savings' or is_saving:
                new_monthly_summary.savings += amount
            else:
                new_monthly_summary.expenses += abs(amount)

            # Recalculate total savings for new month
            new_monthly_summary.savings = new_monthly_summary.income - \
                new_monthly_summary.expenses

            # Update category summaries for old month
            if old_category:
                old_cat_summary = CategorySummary.query.filter_by(
                    user_id=user_id,
                    category=old_category,
                    month=old_month,
                    year=old_year
                ).first()

                if old_cat_summary:
                    old_cat_summary.amount -= abs(old_amount)
                    if old_cat_summary.amount <= 0:
                        db.session.delete(old_cat_summary)

            # Update or create category summary for new month
            new_cat_summary = CategorySummary.query.filter_by(
                user_id=user_id,
                category=category,
                month=new_month,
                year=new_year
            ).first()

            if new_cat_summary:
                prev_amount = new_cat_summary.amount
                new_cat_summary.amount += abs(amount)

                # Update trend
                if new_cat_summary.amount > prev_amount:
                    new_cat_summary.trend = 'increasing'
                elif new_cat_summary.amount < prev_amount:
                    new_cat_summary.trend = 'decreasing'
            else:
                # Create new category summary
                new_cat_summary = CategorySummary(
                    user_id=user_id,
                    category=category,
                    month=new_month,
                    year=new_year,
                    amount=abs(amount),
                    trend='stable'  # Default for a new entry
                )
                db.session.add(new_cat_summary)
        else:
            # Month and year didn't change, update existing monthly summary
            monthly_summary = MonthlySummary.query.filter_by(
                user_id=user_id,
                month=new_month,
                year=new_year
            ).first()

            if monthly_summary:
                # Reverse old transaction impact
                if old_category == 'Savings' or old_is_saving:
                    monthly_summary.savings -= old_amount
                else:
                    monthly_summary.expenses -= abs(old_amount)

                # Apply new transaction impact
                if category == 'Savings' or is_saving:
                    monthly_summary.savings += amount
                else:
                    monthly_summary.expenses += abs(amount)

                # Recalculate total savings
                monthly_summary.savings = monthly_summary.income - monthly_summary.expenses

            # Update category summaries
            # For old category (if different from new category)
            if old_category != category:
                old_cat_summary = CategorySummary.query.filter_by(
                    user_id=user_id,
                    category=old_category,
                    month=new_month,
                    year=new_year
                ).first()

                if old_cat_summary:
                    old_cat_summary.amount -= abs(old_amount)
                    if old_cat_summary.amount <= 0:
                        db.session.delete(old_cat_summary)

            # For new category
            new_cat_summary = CategorySummary.query.filter_by(
                user_id=user_id,
                category=category,
                month=new_month,
                year=new_year
            ).first()

            if new_cat_summary:
                # Only adjust if not the same category or the amount changed
                if old_category != category or old_amount != amount:
                    prev_amount = new_cat_summary.amount
                    if old_category == category:
                        # Same category, just update the difference
                        new_cat_summary.amount += abs(amount) - abs(old_amount)
                    else:
                        # Different category, add the full amount
                        new_cat_summary.amount += abs(amount)

                    # Update trend
                    if new_cat_summary.amount > prev_amount:
                        new_cat_summary.trend = 'increasing'
                    elif new_cat_summary.amount < prev_amount:
                        new_cat_summary.trend = 'decreasing'
            else:
                # Create new category summary
                new_cat_summary = CategorySummary(
                    user_id=user_id,
                    category=category,
                    month=new_month,
                    year=new_year,
                    amount=abs(amount),
                    trend='stable'  # Default for a new entry
                )
                db.session.add(new_cat_summary)

        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": f"Update failed: {str(e)}"})


# Route for deleting a transaction
@app.route('/delete_transaction', methods=['POST'])
def delete_transaction():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "User not logged in"})

    user_id = session['user_id']
    data = request.get_json()

    transaction_id = data['id']

    # Get the transaction
    transaction = Transaction.query.filter_by(
        id=transaction_id, user_id=user_id
    ).first()

    if not transaction:
        return jsonify({"success": False, "message": "Transaction not found"})

    try:
        # Get transaction details to update monthly summary
        amount = transaction.amount
        category = transaction.category
        is_saving = transaction.is_saving

        # Get transaction date
        trans_date = transaction.date
        trans_month = trans_date.month
        trans_year = trans_date.year

        # Update monthly summary
        monthly_summary = MonthlySummary.query.filter_by(
            user_id=user_id,
            month=trans_month,
            year=trans_year
        ).first()

        if monthly_summary:
            # Reverse transaction impact
            if category == 'Savings' or is_saving:
                monthly_summary.savings -= amount
            else:
                monthly_summary.expenses -= abs(amount)

            # Recalculate total savings
            monthly_summary.savings = monthly_summary.income - monthly_summary.expenses

        # Update category summary
        cat_summary = CategorySummary.query.filter_by(
            user_id=user_id,
            category=category,
            month=trans_month,
            year=trans_year
        ).first()

        if cat_summary:
            cat_summary.amount -= abs(amount)
            if cat_summary.amount <= 0:
                db.session.delete(cat_summary)

        # Delete the transaction
        db.session.delete(transaction)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": f"Delete failed: {str(e)}"})

# Route for logging out


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# Monthly report page


@app.route('/monthly_report')
def monthly_report():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Just render the template - data will be loaded via AJAX
    return render_template('monthly_report.html')



@app.route('/ml_prediction')
def ml_prediction_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Get categories for the dropdown
    categories = Transaction.CATEGORIES

    # Just render the template - data will be loaded via AJAX
    return render_template('ml_prediction.html', categories=categories)

# Route to fetch data for ML training

@app.route('/train_monthly_model', methods=['POST'])
def train_monthly_model():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "User not logged in"})

    user_id = session['user_id']
    category = request.form.get('category')

    if not category:
        return jsonify({"success": False, "message": "Category is required"})

    try:
        # Get all transactions in the selected category
        transactions = Transaction.query.filter_by(
            user_id=user_id,
            category=category
        ).all()

        if len(transactions) < 5:  # Need minimum data points for meaningful prediction
            return jsonify({
                "success": False,
                "message": f"Not enough data for {category}. Need at least 5 transactions."
            })

        # Organize data by month
        monthly_spending = defaultdict(float)
        for transaction in transactions:
            month_key = f"{transaction.date.year}-{transaction.date.month:02d}"
            monthly_spending[month_key] += abs(transaction.amount)

        # Need at least 3 months of data for meaningful monthly prediction
        if len(monthly_spending) < 3:
            return jsonify({
                "success": False,
                "message": f"Need data from at least 3 different months for {category} to predict monthly spending."
            })

        # Extract features (year, month) and target (total monthly amount)
        X = []  # Features
        y = []  # Target values
        
        for month_key, total_amount in monthly_spending.items():
            year, month = map(int, month_key.split('-'))
            # Features: year, month, previous year's same month (if available)
            features = [year, month]
            
            # Try to add seasonal pattern by looking at previous year's same month
            prev_year_key = f"{year-1}-{month:02d}"
            if prev_year_key in monthly_spending:
                features.append(monthly_spending[prev_year_key])
            else:
                features.append(0)  # No data for previous year
                
            X.append(features)
            y.append(total_amount)

        # Convert to numpy arrays
        X = np.array(X)
        y = np.array(y)

        # Train a Gradient Boosting Regressor
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.model_selection import train_test_split, cross_val_score
        
        # If we have enough data, use cross-validation
        if len(X) >= 6:
            model = GradientBoostingRegressor(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=3,
                random_state=42
            )
            # Use cross-validation to get a better estimate of model performance
            cv_scores = cross_val_score(model, X, y, cv=min(5, len(X)), scoring='r2')
            model.fit(X, y)  # Fit on all data
            score = np.mean(cv_scores)
        else:
            # If less data, use all for training
            model = GradientBoostingRegressor(
                n_estimators=50,
                learning_rate=0.1,
                max_depth=2,
                random_state=42
            )
            model.fit(X, y)
            # Calculate model score on training data
            score = model.score(X, y)

        # Create directory for storing models if it doesn't exist
        model_dir = os.path.join('static', 'models')
        os.makedirs(model_dir, exist_ok=True)

        # Save the model
        model_filename = os.path.join(
            model_dir, f'user_{user_id}_monthly_{category.lower().replace(" ", "_")}.pkl')
        with open(model_filename, 'wb') as f:
            pickle.dump(model, f)

        # Add a note about limited data if appropriate
        note = ""
        if len(X) < 6:
            note = " (Note: Limited monthly data available - accuracy may improve with more months)"

        return jsonify({
            "success": True,
            "message": f"Monthly prediction model trained successfully for {category}!",
            "accuracy": f"{score:.2f}{note}"
        })

    except Exception as e:
        return jsonify({"success": False, "message": f"Error training monthly model: {str(e)}"})

@app.route('/predict_monthly_spending', methods=['POST'])
def predict_monthly_spending():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "User not logged in"})

    user_id = session['user_id']
    category = request.form.get('category')
    year_month = request.form.get('year_month')  # Format: YYYY-MM

    if not category or not year_month:
        return jsonify({"success": False, "message": "Category and month are required"})

    try:
        # Parse the year and month
        year, month = map(int, year_month.split('-'))

        # Check if model exists
        model_dir = os.path.join('static', 'models')
        model_filename = os.path.join(
            model_dir, f'user_{user_id}_monthly_{category.lower().replace(" ", "_")}.pkl')

        if not os.path.exists(model_filename):
            return jsonify({
                "success": False,
                "message": f"No monthly model found for {category}. Please train a model first."
            })

        # Load the model
        with open(model_filename, 'rb') as f:
            model = pickle.load(f)

        # Get transactions for previous year same month if available
        prev_year_amount = 0
        prev_year_month = f"{year-1}-{month:02d}-01"
        prev_year_month_end = f"{year-1}-{month:02d}-28"  # Simplified for demonstration
        
        prev_year_transactions = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.category == category,
            Transaction.date >= prev_year_month,
            Transaction.date <= prev_year_month_end
        ).all()
        
        if prev_year_transactions:
            prev_year_amount = sum(abs(t.amount) for t in prev_year_transactions)

        # Make prediction
        features = np.array([[year, month, prev_year_amount]])
        prediction = model.predict(features)[0]

        # Get current month's spending for comparison
        current_month_transactions = Transaction.query.filter(
            Transaction.user_id == user_id,
            Transaction.category == category,
            extract('year', Transaction.date) == year,
            extract('month', Transaction.date) == month
        ).all()
        
        current_spending = sum(abs(t.amount) for t in current_month_transactions)
        
        # Calculate remaining budget
        remaining = prediction - current_spending if prediction > current_spending else 0

        month_name = datetime(year, month, 1).strftime('%B')
        
        return jsonify({
            "success": True,
            "prediction": round(prediction, 2),
            "current_spending": round(current_spending, 2),
            "remaining": round(remaining, 2),
            "category": category,
            "month": month_name,
            "year": year
        })

    except Exception as e:
        return jsonify({"success": False, "message": f"Error making monthly prediction: {str(e)}"})

@app.route('/get_monthly_data')
def get_monthly_data():
    if 'user_id' not in session:
        return jsonify({"error": "User not logged in"})

    user_id = session['user_id']
    
    try:
        # Get all user transactions
        transactions = Transaction.query.filter_by(user_id=user_id).all()
        
        if not transactions:
            return jsonify({"success": False, "message": "No transaction data available"})
            
        # Organize data by month and category
        monthly_data = defaultdict(lambda: defaultdict(float))
        categories = set()
        
        for transaction in transactions:
            month_key = f"{transaction.date.year}-{transaction.date.month:02d}"
            monthly_data[month_key][transaction.category] += abs(transaction.amount)
            categories.add(transaction.category)
            
        # Convert to list format for response
        formatted_data = []
        for month_key, category_amounts in monthly_data.items():
            year, month = month_key.split('-')
            month_name = datetime(int(year), int(month), 1).strftime('%B %Y')
            
            month_item = {
                "month_key": month_key,
                "month_name": month_name,
                "total": sum(category_amounts.values()),
                "categories": {}
            }
            
            for category in categories:
                month_item["categories"][category] = category_amounts.get(category, 0)
                
            formatted_data.append(month_item)
            
        # Sort by date
        formatted_data.sort(key=lambda x: x["month_key"])
        
        return jsonify({
            "success": True, 
            "data": formatted_data,
            "categories": list(categories)
        })
        
    except Exception as e:
        return jsonify({"success": False, "message": f"Error fetching monthly data: {str(e)}"})

# Create the database tables
with app.app_context():
    db.create_all()


if __name__ == '__main__':
    app.run(debug=True)
