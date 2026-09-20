"""
====================================================
  NexaBank — Banking System Backend (Flask + MySQL)
  DBMS Mini Project

  Features:
  - Customer registration/login
  - Manager & Staff registration/login
  - Customer approval workflow:
      Customer registers -> Staff approval -> Manager approval -> Account active
  - Deposit, withdraw, transfer
  - Loan management with EMI
  - Transaction history
====================================================
  Requirements:
    pip install flask flask-cors mysql-connector-python

  Run:
    python banking_backend_roles.py

  API Base:
    http://localhost:5000/api
====================================================
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
import hashlib
import random

app = Flask(__name__)
CORS(app)

# ─── DB CONNECTION ──────────────────────────────────────
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "shaik6162",   # change if your MySQL password is different
    "database": "nexabank_db"
}


def get_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        print("MySQL Connected Successfully")
        return conn
    except Exception as e:
        print("Database Connection Error:", e)
        raise


def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()


# ─── IST TIME HELPERS ───────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

def ist_now():
    """Current Indian Standard Time as naive datetime for MySQL."""
    return datetime.now(IST).replace(tzinfo=None)

def ist_today():
    return ist_now().date()


def clean_json_value(value):
    """Convert Decimal/date/datetime values so Flask can safely return JSON."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def clean_json(data):
    if isinstance(data, list):
        return [clean_json(item) for item in data]
    if isinstance(data, dict):
        return {key: clean_json_value(value) for key, value in data.items()}
    return clean_json_value(data)



# ─── TRANSACTION REFERENCE HELPER ───────────────────────
def generate_transaction_ref(prefix="TXN"):
    """Creates unique transaction reference like TXN202605181234567890."""
    return f"{prefix}{ist_now().strftime('%Y%m%d%H%M%S')}{random.randint(1000,9999)}"


def insert_transaction(cur, account_id, transaction_type, amount, balance_after,
                       description, reference_account=None, transfer_mode=None,
                       status="completed"):
    """
    Inserts transaction with unique transaction_ref if DB column exists.
    If old DB does not have transaction_ref, it falls back safely.
    """
    txn_ref = generate_transaction_ref()
    try:
        cur.execute("""
            INSERT INTO transactions
            (transaction_ref, account_id, transaction_type, amount, balance_after,
             description, reference_account, transfer_mode, status, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            txn_ref, account_id, transaction_type, amount, balance_after,
            description, reference_account, transfer_mode, status, ist_now()
        ))
    except Exception as e:
        # Fallback for older schema without transaction_ref column
        if "transaction_ref" not in str(e):
            raise
        cur.execute("""
            INSERT INTO transactions
            (account_id, transaction_type, amount, balance_after,
             description, reference_account, transfer_mode, status, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            account_id, transaction_type, amount, balance_after,
            description, reference_account, transfer_mode, status, ist_now()
        ))
    return txn_ref

# ─── HELPER RESPONSE FUNCTIONS ──────────────────────────
def success(data=None, msg="Success"):
    return jsonify({"status": "success", "message": msg, "data": clean_json(data)})


def error(msg="Error", code=400):
    return jsonify({"status": "error", "message": msg}), code


# ════════════════════════════════════════════════════════
#   CUSTOMER AUTH ROUTES
# ════════════════════════════════════════════════════════

@app.route("/api/register", methods=["POST"])
def register():
    """
    Customer registration. Same email can create one Savings and one Current account.
    Existing email requires same password and creates only the missing account type.
    """
    d = request.json or {}
    required = ["full_name", "email", "phone", "password", "dob", "address", "account_type"]
    if not all(k in d and str(d[k]).strip() for k in required):
        return error("Missing required fields")

    account_type = d.get("account_type")
    if account_type not in ["savings", "current"]:
        return error("Account type must be savings or current")

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        email = d["email"].strip()
        pwd_hash = hash_password(d["password"])
        cur.execute("""
            SELECT customer_id, password_hash, staff_approval, manager_approval, approval_status
            FROM customers
            WHERE email = %s
        """, (email,))
        existing = cur.fetchone()

        if existing:
            if existing["password_hash"] != pwd_hash:
                return error("This email already exists. Use same password to add another account type.", 409)

            cust_id = existing["customer_id"]

            cur.execute("""
                SELECT account_id
                FROM accounts
                WHERE customer_id=%s AND account_type=%s
            """, (cust_id, account_type))

            if cur.fetchone():
                return error(f"{account_type.capitalize()} account already exists for this email", 409)

            new_account_status = "active" if (
                existing["staff_approval"] == "accepted"
                and existing["manager_approval"] == "accepted"
                and existing["approval_status"] == "approved"
            ) else "inactive"
        else:
            new_account_status = "inactive"
            cur.execute("""
                INSERT INTO customers
                (full_name, email, phone, password_hash, dob, address,
                 kyc_status, staff_approval, manager_approval, approval_status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s,
                        'pending', 'pending', 'pending', 'pending', %s)
            """, (
                d["full_name"].strip(), email, d["phone"].strip(), pwd_hash,
                d["dob"], d["address"].strip(), ist_now()
            ))
            cust_id = cur.lastrowid

        acc_no = "NEXA" + ist_now().strftime("%H%M%S%f")[-7:]
        opening = Decimal(str(d.get("opening_balance", 0)))
        cur.execute("""
            INSERT INTO accounts
            (account_number, customer_id, account_type, balance, branch, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (acc_no, cust_id, account_type, opening, d.get("branch", "Main Branch"), new_account_status, ist_now()))
        conn.commit()
        return success({"account_number": acc_no, "customer_id": cust_id, "account_type": account_type},
                       "Account request submitted. Wait for staff and manager approval.")
    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()


@app.route("/api/login", methods=["POST"])
def login():
    """
    Customer login.
    Supports multiple accounts under the same email.
    Optional frontend fields:
    - account_type: "savings" or "current"
    - account_number: exact account number
    If neither is sent, the first active account is returned and all accounts are included.
    """
    d = request.json or {}
    email = d.get("email")
    password = d.get("password")
    account_type = d.get("account_type")
    account_number = d.get("account_number")

    if not email or not password:
        return error("Email and password are required")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT customer_id, full_name, email, phone, dob, address,
                   kyc_status, staff_approval, manager_approval, approval_status,
                   created_at
            FROM customers
            WHERE email = %s AND password_hash = %s
            LIMIT 1
        """, (email.strip(), hash_password(password)))

        customer = cur.fetchone()

        if not customer:
            return error("Invalid credentials", 401)

        if customer["approval_status"] == "rejected":
            return error("Your registration request was rejected. Contact branch support.", 403)

        if customer["staff_approval"] != "accepted" or customer["manager_approval"] != "accepted":
            return error("Your account is pending staff and manager approval.", 403)

        query = """
            SELECT account_id, account_number, account_type, balance,
                   branch, status AS account_status, created_at
            FROM accounts
            WHERE customer_id = %s
        """
        params = [customer["customer_id"]]

        if account_number:
            query += " AND account_number = %s"
            params.append(account_number)
        elif account_type:
            query += " AND account_type = %s"
            params.append(account_type)

        query += " ORDER BY account_type ASC, created_at DESC"

        cur.execute(query, tuple(params))
        accounts = cur.fetchall()

        if not accounts:
            return error("No account found for this login", 404)

        active_accounts = [a for a in accounts if a["account_status"] == "active"]

        if not active_accounts:
            return error("Your account is not active yet.", 403)

        selected_account = active_accounts[0]
        user = {**customer, **selected_account, "accounts": accounts}

        return success(user, "Login successful")

    finally:
        cur.close()
        conn.close()


# ════════════════════════════════════════════════════════
#   MANAGER / STAFF AUTH ROUTES
# ════════════════════════════════════════════════════════

@app.route("/api/admin/register", methods=["POST"])
def admin_register():
    """
    Register manager or staff.
    Frontend should send:
    {
      "full_name": "...",
      "email": "...",
      "phone": "...",
      "password": "...",
      "branch": "Main Branch",
      "role": "manager" OR "staff"
    }
    """
    d = request.json or {}
    required = ["full_name", "email", "phone", "password", "role"]

    if not all(k in d and str(d[k]).strip() for k in required):
        return error("Missing required fields")

    role = d.get("role")
    if role not in ["manager", "staff"]:
        return error("Role must be manager or staff")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("SELECT admin_id FROM admins WHERE email=%s", (d["email"].strip(),))
        if cur.fetchone():
            return error("Email already registered")

        cur.execute("""
            INSERT INTO admins
            (full_name, email, phone, password_hash, branch, role, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'active')
        """, (
            d["full_name"].strip(),
            d["email"].strip(),
            d["phone"].strip(),
            hash_password(d["password"]),
            d.get("branch", "Main Branch"),
            role
        ))

        conn.commit()
        return success({"role": role}, f"{role.capitalize()} registration successful")

    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    """
    Manager/staff login.
    Frontend should send email/password.
    """
    d = request.json or {}
    email = d.get("email")
    password = d.get("password")

    if not email or not password:
        return error("Email and password are required")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT admin_id, full_name, email, phone, branch, role, status, created_at
            FROM admins
            WHERE email=%s AND password_hash=%s
            LIMIT 1
        """, (email.strip(), hash_password(password)))

        admin = cur.fetchone()

        if not admin:
            return error("Invalid manager/staff credentials", 401)

        if admin["status"] != "active":
            return error("This manager/staff account is inactive", 403)

        return success(admin, "Login successful")

    finally:
        cur.close()
        conn.close()


# ════════════════════════════════════════════════════════
#   APPROVAL WORKFLOW ROUTES
# ════════════════════════════════════════════════════════

def check_customer_approval(customer_id):

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT staff_approval, manager_approval
            FROM customers
            WHERE customer_id=%s
        """, (customer_id,))

        row = cur.fetchone()

        if row:

            staff_ok = str(row["staff_approval"]).lower() == "accepted"
            manager_ok = str(row["manager_approval"]).lower() == "accepted"

            # BOTH APPROVED
            if staff_ok and manager_ok:

                # UPDATE CUSTOMER STATUS
                cur.execute("""
                    UPDATE customers
                    SET approval_status='approved',
                        kyc_status='verified'
                    WHERE customer_id=%s
                """, (customer_id,))

                # ACTIVATE ACCOUNT
                cur.execute("""
                    UPDATE accounts
                    SET status='active'
                    WHERE customer_id=%s
                """, (customer_id,))

                print(f"Customer {customer_id} approved and activated")

        conn.commit()

    except Exception as e:
        conn.rollback()
        print("Approval Error:", e)

    finally:
        cur.close()
        conn.close()


@app.route("/api/admin/pending-customers", methods=["GET"])
def pending_customers():
    """
    Shows customers waiting for approval.
    Both manager and staff dashboards can use this.
    """
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT c.customer_id, c.full_name, c.email, c.phone, c.dob, c.address,
                   c.kyc_status, c.staff_approval, c.manager_approval, c.approval_status,
                   c.created_at,
                   a.account_id, a.account_number, a.account_type, a.balance,
                   a.branch, a.status AS account_status
            FROM customers c
            JOIN accounts a ON c.customer_id = a.customer_id
            WHERE c.approval_status = 'pending'
            ORDER BY c.customer_id DESC
        """)
        rows = cur.fetchall()
        return success(rows)

    except Exception as e:
        return error(str(e))
    finally:
        cur.close()
        conn.close()


@app.route("/api/admin/customers", methods=["GET"])
def all_customers_for_admin():
    """
    Manager/staff can see all customers.
    Frontend can filter/display according to role.
    """
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT c.customer_id, c.full_name, c.email, c.phone, c.dob, c.address,
                   c.kyc_status, c.staff_approval, c.manager_approval, c.approval_status,
                   c.created_at,
                   a.account_id, a.account_number, a.account_type, a.balance,
                   a.branch, a.status AS account_status
            FROM customers c
            JOIN accounts a ON c.customer_id = a.customer_id
            ORDER BY c.customer_id DESC
        """)
        rows = cur.fetchall()
        return success(rows)
    except Exception as e:
        return error(str(e))
    finally:
        cur.close()
        conn.close()


@app.route("/api/staff/customer-decision", methods=["POST"])
def staff_customer_decision():
    """
    Staff accepts or rejects customer registration.
    JSON:
    {
      "customer_id": 1,
      "decision": "accepted" OR "rejected"
    }
    """
    d = request.json or {}
    customer_id = d.get("customer_id")
    decision = d.get("decision")

    if decision not in ["accepted", "rejected"]:
        return error("Decision must be accepted or rejected")

    conn = get_db()
    cur = conn.cursor()

    try:
        if decision == "rejected":
            cur.execute("""
                UPDATE customers
                SET staff_approval='rejected',
                    approval_status='rejected',
                    kyc_status='rejected'
                WHERE customer_id=%s
            """, (customer_id,))
            cur.execute("""
                UPDATE accounts
                SET status='inactive'
                WHERE customer_id=%s
            """, (customer_id,))
        else:
            cur.execute("""
                UPDATE customers
                SET staff_approval='accepted'
                WHERE customer_id=%s
            """, (customer_id,))

        conn.commit()
        check_customer_approval(customer_id)

    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()

    if decision == "accepted":
        check_customer_approval(customer_id)

    return success(msg=f"Staff {decision} customer request")


@app.route("/api/manager/customer-decision", methods=["POST"])
def manager_customer_decision():
    """
    Manager accepts or rejects customer registration.
    JSON:
    {
      "customer_id": 1,
      "decision": "accepted" OR "rejected"
    }
    """
    d = request.json or {}
    customer_id = d.get("customer_id")
    decision = d.get("decision")

    if decision not in ["accepted", "rejected"]:
        return error("Decision must be accepted or rejected")

    conn = get_db()
    cur = conn.cursor()

    try:
        if decision == "rejected":
            cur.execute("""
                UPDATE customers
                SET manager_approval='rejected',
                    approval_status='rejected',
                    kyc_status='rejected'
                WHERE customer_id=%s
            """, (customer_id,))
            cur.execute("""
                UPDATE accounts
                SET status='inactive'
                WHERE customer_id=%s
            """, (customer_id,))
        else:
            cur.execute("""
                UPDATE customers
                SET manager_approval='accepted'
                WHERE customer_id=%s
            """, (customer_id,))

        conn.commit()
        check_customer_approval(customer_id)

    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()

    if decision == "accepted":
        check_customer_approval(customer_id)

    return success(msg=f"Manager {decision} customer request")


# ════════════════════════════════════════════════════════
#   ACCOUNT ROUTES
# ════════════════════════════════════════════════════════

@app.route("/api/accounts/<int:customer_id>", methods=["GET"])
def get_accounts(customer_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT account_id, account_number, account_type, balance, branch, status, created_at
        FROM accounts
        WHERE customer_id = %s
        ORDER BY created_at DESC
    """, (customer_id,))
    accounts = cur.fetchall()
    cur.close()
    conn.close()
    return success(accounts)



@app.route("/api/account/create", methods=["POST"])
def create_extra_account():
    """
    Create Savings/Current account for an already registered customer.
    Same customer can have one savings and one current account.
    If the customer is already approved, the new account becomes active immediately.
    """
    d = request.json or {}

    customer_id = d.get("customer_id")
    account_type = d.get("account_type")
    opening = Decimal(str(d.get("opening_balance", 0)))
    branch = d.get("branch", "Main Branch")

    if not customer_id:
        return error("Customer ID is required")
    if account_type not in ["savings", "current"]:
        return error("Account type must be savings or current")
    if opening < 0:
        return error("Opening balance cannot be negative")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT customer_id, staff_approval, manager_approval, approval_status
            FROM customers
            WHERE customer_id=%s
        """, (customer_id,))
        customer = cur.fetchone()

        if not customer:
            return error("Customer not found", 404)

        cur.execute("""
            SELECT account_id
            FROM accounts
            WHERE customer_id=%s AND account_type=%s
        """, (customer_id, account_type))

        if cur.fetchone():
            return error(f"{account_type.capitalize()} account already exists", 409)

        status = "active" if (
            customer["staff_approval"] == "accepted"
            and customer["manager_approval"] == "accepted"
            and customer["approval_status"] == "approved"
        ) else "inactive"

        acc_no = "NEXA" + ist_now().strftime("%H%M%S%f")[-7:]

        cur.execute("""
            INSERT INTO accounts
            (account_number, customer_id, account_type, balance, branch, status, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (acc_no, customer_id, account_type, opening, branch, status, ist_now()))

        conn.commit()

        return success({
            "account_number": acc_no,
            "customer_id": customer_id,
            "account_type": account_type,
            "status": status
        }, f"{account_type.capitalize()} account created successfully")

    except Exception as e:
        conn.rollback()
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()


@app.route("/api/account/balance/<string:acc_no>", methods=["GET"])
def get_balance(acc_no):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT a.account_number, a.balance, c.full_name, a.account_type
        FROM accounts a
        JOIN customers c ON a.customer_id = c.customer_id
        WHERE a.account_number = %s AND a.status = 'active'
    """, (acc_no,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return error("Account not found", 404)
    return success(row)


# ════════════════════════════════════════════════════════
#   TRANSACTION ROUTES
# ════════════════════════════════════════════════════════


@app.route("/api/deposit", methods=["POST"])
def deposit():
    """Direct customer deposit with transaction ID and IST date/time."""
    d = request.json or {}
    acc_no = d.get("account_number")
    amount = Decimal(str(d.get("amount", 0)))
    description = d.get("description", "Cash Deposit")
    if amount <= 0:
        return error("Amount must be positive")
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT account_id, balance FROM accounts WHERE account_number=%s AND status='active'", (acc_no,))
        acc = cur.fetchone()
        if not acc:
            return error("Account not found or not active", 404)
        new_balance = Decimal(str(acc["balance"])) + amount
        cur.execute("UPDATE accounts SET balance=%s WHERE account_id=%s", (new_balance, acc["account_id"]))
        txn_ref = insert_transaction(cur, acc["account_id"], "deposit", amount, new_balance, description)
        conn.commit()
        return success({"new_balance": new_balance, "transaction_ref": txn_ref, "transaction_time": ist_now()},
                       f"₹{float(amount):,.2f} deposited successfully")
    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()


@app.route("/api/deposit/request", methods=["POST"])
def deposit_request_removed():
    return deposit()


@app.route("/api/staff/pending-deposits", methods=["GET"])
def pending_deposits():
    return success([], "Deposit staff approval removed. Deposits are direct transactions now.")


@app.route("/api/staff/deposit-decision", methods=["POST"])
def deposit_decision():
    return error("Deposit staff approval removed. Deposits are direct transactions now.", 410)


@app.route("/api/withdraw", methods=["POST"])
def withdraw():
    """Direct customer withdrawal with transaction ID and IST date/time."""
    d = request.json or {}
    acc_no = d.get("account_number")
    amount = Decimal(str(d.get("amount", 0)))
    description = d.get("description", "Cash Withdrawal")
    if amount <= 0:
        return error("Amount must be positive")
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT account_id, balance FROM accounts WHERE account_number=%s AND status='active'", (acc_no,))
        acc = cur.fetchone()
        if not acc:
            return error("Account not found or not active", 404)
        current_balance = Decimal(str(acc["balance"]))
        if current_balance < amount:
            return error("Insufficient funds")
        new_balance = current_balance - amount
        cur.execute("UPDATE accounts SET balance=%s WHERE account_id=%s", (new_balance, acc["account_id"]))
        txn_ref = insert_transaction(cur, acc["account_id"], "withdrawal", amount, new_balance, description)
        conn.commit()
        return success({"new_balance": new_balance, "transaction_ref": txn_ref, "transaction_time": ist_now()},
                       f"₹{float(amount):,.2f} withdrawn successfully")
    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()


@app.route("/api/withdraw/request", methods=["POST"])
def withdraw_request_removed():
    return withdraw()


@app.route("/api/staff/pending-withdrawals", methods=["GET"])
def pending_withdrawals():
    return success([], "Withdrawal staff approval removed. Withdrawals are direct transactions now.")


@app.route("/api/staff/withdraw-decision", methods=["POST"])
def withdraw_decision():
    return error("Withdrawal staff approval removed. Withdrawals are direct transactions now.", 410)


@app.route("/api/transfer", methods=["POST"])

def transfer():
    d = request.json or {}
    from_acc = d.get("from_account")
    to_acc = d.get("to_account")
    amount = Decimal(str(d.get("amount", 0)))
    mode = d.get("mode", "IMPS")

    if amount <= 0:
        return error("Amount must be positive")
    if from_acc == to_acc:
        return error("Cannot transfer to same account")
    if mode == "RTGS" and amount < Decimal("200000"):
        return error("RTGS minimum amount is ₹2,00,000")

    conn = get_db()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT account_id, balance FROM accounts WHERE account_number=%s AND status='active'", (from_acc,))
        sender = cur.fetchone()
        if not sender:
            return error("Sender account not found or not active", 404)

        sender_balance = Decimal(str(sender["balance"]))
        if sender_balance < amount:
            return error("Insufficient funds")

        cur.execute("SELECT account_id, balance FROM accounts WHERE account_number=%s AND status='active'", (to_acc,))
        receiver = cur.fetchone()
        if not receiver:
            return error("Receiver account not found or not active", 404)

        receiver_balance = Decimal(str(receiver["balance"]))
        new_sender_bal = sender_balance - amount
        new_receiver_bal = receiver_balance + amount

        cur.execute("UPDATE accounts SET balance=%s WHERE account_id=%s", (new_sender_bal, sender["account_id"]))
        out_ref = insert_transaction(
            cur, sender["account_id"], "transfer_out", amount, new_sender_bal,
            f"{mode} Transfer to {to_acc}", to_acc, mode
        )

        cur.execute("UPDATE accounts SET balance=%s WHERE account_id=%s", (new_receiver_bal, receiver["account_id"]))
        in_ref = insert_transaction(
            cur, receiver["account_id"], "transfer_in", amount, new_receiver_bal,
            f"{mode} Transfer from {from_acc}", from_acc, mode
        )

        conn.commit()
        return success({
            "sender_new_balance": new_sender_bal,
            "receiver_new_balance": new_receiver_bal,
            "sender_transaction_ref": out_ref,
            "receiver_transaction_ref": in_ref
        }, f"₹{float(amount):,.2f} transferred via {mode} successfully")
    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()


@app.route("/api/transactions/<int:account_id>", methods=["GET"])
def get_transactions(account_id):
    """
    Customer transaction history.
    Includes:
    - unique transaction_ref
    - date/time created_at
    - customer_name/account_number
    - reference_customer_name for transfers
    """
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 10))
    offset = (page - 1) * limit

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT
                t.transaction_id,
                t.transaction_ref,
                c.full_name AS customer_name,
                a.account_number,
                t.transaction_type,
                t.amount,
                t.balance_after,
                t.description,
                t.reference_account,
                rc.full_name AS reference_customer_name,
                t.transfer_mode,
                t.status,
                t.created_at
            FROM transactions t
            JOIN accounts a ON t.account_id = a.account_id
            JOIN customers c ON a.customer_id = c.customer_id
            LEFT JOIN accounts ra ON t.reference_account = ra.account_number
            LEFT JOIN customers rc ON ra.customer_id = rc.customer_id
            WHERE t.account_id = %s
            ORDER BY t.created_at DESC
            LIMIT %s OFFSET %s
        """, (account_id, limit, offset))

        rows = cur.fetchall()

        cur.execute("SELECT COUNT(*) as total FROM transactions WHERE account_id=%s", (account_id,))
        total = cur.fetchone()["total"]

        return success({"transactions": rows, "total": total, "page": page, "limit": limit})

    except Exception as e:
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()


# ════════════════════════════════════════════════════════
#   CUSTOMER ROUTES
# ════════════════════════════════════════════════════════

@app.route("/api/customer/<int:customer_id>", methods=["GET"])
def get_customer(customer_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT customer_id, full_name, email, phone, dob, address,
               kyc_status, staff_approval, manager_approval, approval_status, created_at
        FROM customers WHERE customer_id = %s
    """, (customer_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return error("Customer not found", 404)
    return success(row)


@app.route("/api/customer/<int:customer_id>", methods=["PUT"])
def update_customer(customer_id):
    d = request.json or {}
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE customers SET phone=%s, address=%s WHERE customer_id=%s",
        (d.get("phone"), d.get("address"), customer_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return success(msg="Profile updated")


# ════════════════════════════════════════════════════════
#   LOAN ROUTES
# ════════════════════════════════════════════════════════

def calculate_emi(principal, annual_rate, tenure_months):
    principal = Decimal(str(principal))
    annual_rate = Decimal(str(annual_rate))
    tenure_months = int(tenure_months)

    if tenure_months <= 0:
        raise ValueError("Tenure must be greater than 0")

    monthly_rate = annual_rate / Decimal("12") / Decimal("100")

    if monthly_rate == 0:
        return (principal / Decimal(tenure_months)).quantize(Decimal("0.01"))

    factor = (Decimal("1") + monthly_rate) ** tenure_months
    emi = principal * monthly_rate * factor / (factor - Decimal("1"))
    return emi.quantize(Decimal("0.01"))


def get_interest_rate_for_loan(loan_type):
    rates = {
        "personal": Decimal("12.00"),
        "home": Decimal("8.50"),
        "education": Decimal("7.50"),
        "vehicle": Decimal("9.00"),
        "gold": Decimal("10.00")
    }
    return rates.get(loan_type, Decimal("10.00"))


@app.route("/api/loan/emi-preview", methods=["POST"])
def loan_emi_preview():
    d = request.json or {}
    try:
        loan_type = d.get("loan_type", "personal")
        principal = Decimal(str(d.get("principal_amount", 0)))
        tenure = int(d.get("tenure_months", 0))

        if principal <= 0:
            return error("Loan amount must be positive")
        if tenure <= 0:
            return error("Tenure must be positive")

        annual_rate = get_interest_rate_for_loan(loan_type)
        emi = calculate_emi(principal, annual_rate, tenure)
        total_payable = (emi * Decimal(tenure)).quantize(Decimal("0.01"))
        total_interest = (total_payable - principal).quantize(Decimal("0.01"))

        return success({
            "loan_type": loan_type,
            "principal_amount": principal,
            "interest_rate": annual_rate,
            "tenure_months": tenure,
            "emi_amount": emi,
            "total_payable": total_payable,
            "total_interest": total_interest
        }, "EMI calculated successfully")

    except Exception as e:
        return error(str(e))


@app.route("/api/loan/apply", methods=["POST"])
def apply_loan():
    d = request.json or {}

    try:
        customer_id = d.get("customer_id")
        account_number = d.get("account_number")
        loan_type = d.get("loan_type")
        principal = Decimal(str(d.get("principal_amount", 0)))
        tenure = int(d.get("tenure_months", 0))

        if not customer_id:
            return error("Customer ID is required")

        if not account_number:
            return error("Account number is required")

        if loan_type not in ["personal", "home", "education", "vehicle", "gold"]:
            return error("Invalid loan type")

        if principal <= 0:
            return error("Loan amount must be positive")

        if tenure <= 0:
            return error("Tenure must be positive")

        annual_rate = get_interest_rate_for_loan(loan_type)
        emi = calculate_emi(principal, annual_rate, tenure)
        total_payable = (emi * Decimal(tenure)).quantize(Decimal("0.01"))

        conn = get_db()
        cur = conn.cursor(dictionary=True)

        try:
            cur.execute("""
                SELECT account_id, status
                FROM accounts
                WHERE account_number = %s
                  AND customer_id = %s
                LIMIT 1
            """, (account_number, customer_id))

            acc = cur.fetchone()

            if not acc:
                return error("Invalid account number", 404)

            if acc["status"] != "active":
                return error("Selected account is not active", 403)

            cur.execute("""
                INSERT INTO loans
                (
                    customer_id,
                    account_id,
                    loan_type,
                    principal_amount,
                    interest_rate,
                    tenure_months,
                    emi_amount,
                    total_payable,
                    outstanding,
                    status
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'applied')
            """, (
                customer_id,
                acc["account_id"],
                loan_type,
                principal,
                annual_rate,
                tenure,
                emi,
                total_payable,
                principal
            ))

            loan_id = cur.lastrowid
            conn.commit()

            return success({
                "loan_id": loan_id,
                "account_number": account_number,
                "loan_type": loan_type,
                "principal_amount": principal,
                "interest_rate": annual_rate,
                "tenure_months": tenure,
                "emi_amount": emi,
                "total_payable": total_payable,
                "outstanding": principal,
                "status": "applied"
            }, "Loan application submitted successfully. Waiting for manager approval.")

        except Exception as e:
            conn.rollback()
            return error(str(e))

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        return error(str(e))


@app.route("/api/loans/<int:customer_id>", methods=["GET"])
def get_loans(customer_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT loan_id, customer_id, loan_type, principal_amount, interest_rate,
                   tenure_months, emi_amount, total_payable, outstanding, emi_paid_count,
                   disbursed_on, approved_at, loan_clear_date, next_emi_date, status, created_at
            FROM loans
            WHERE customer_id = %s
            ORDER BY created_at DESC
        """, (customer_id,))
        loans = cur.fetchall()
        return success(loans)
    except Exception as e:
        return error(str(e))
    finally:
        cur.close()
        conn.close()


@app.route("/api/loan/<int:loan_id>/pay-emi", methods=["POST"])
def pay_loan_emi(loan_id):
    d = request.json or {}
    account_number = d.get("account_number")

    if not account_number:
        return error("Account number is required")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT loan_id, customer_id, emi_amount, outstanding, status
            FROM loans
            WHERE loan_id = %s AND status IN ('approved', 'active', 'applied')
        """, (loan_id,))
        loan = cur.fetchone()
        if not loan:
            return error("Loan not found or already closed", 404)

        emi = Decimal(str(loan["emi_amount"]))
        outstanding = Decimal(str(loan["outstanding"]))
        pay_amount = min(emi, outstanding)

        cur.execute("""
            SELECT account_id, balance
            FROM accounts
            WHERE account_number=%s AND customer_id=%s AND status='active'
        """, (account_number, loan["customer_id"]))
        acc = cur.fetchone()
        if not acc:
            return error("Account not found for this customer", 404)

        balance = Decimal(str(acc["balance"]))
        if balance < pay_amount:
            return error("Insufficient account balance for EMI payment")

        new_balance = balance - pay_amount
        new_outstanding = outstanding - pay_amount
        new_status = "closed" if new_outstanding <= 0 else "active"

        cur.execute("UPDATE accounts SET balance=%s WHERE account_id=%s",
                    (new_balance, acc["account_id"]))

        cur.execute("""
            UPDATE loans
            SET outstanding=%s,
                status=%s,
                emi_paid_count = emi_paid_count + 1,
                next_emi_date = DATE_ADD(CURDATE(), INTERVAL 1 MONTH)
            WHERE loan_id=%s
        """, (new_outstanding, new_status, loan_id))

        txn_ref = insert_transaction(
            cur, acc["account_id"], "emi_payment", pay_amount, new_balance,
            f"Loan EMI payment for Loan #{loan_id}"
        )

        conn.commit()
        return success({
            "new_balance": new_balance,
            "new_outstanding": new_outstanding,
            "loan_status": new_status,
            "transaction_ref": txn_ref
        }, "EMI paid successfully")

    except Exception as e:
        conn.rollback()
        return error(str(e))
    finally:
        cur.close()
        conn.close()

@app.route("/api/admin/pending-loans", methods=["GET"])
def pending_loans():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT l.loan_id, c.full_name, c.email, a.account_number,
                   l.loan_type, l.principal_amount, l.emi_amount, l.status, l.created_at
            FROM loans l
            JOIN customers c ON l.customer_id = c.customer_id
            JOIN accounts a ON l.account_id = a.account_id
            WHERE l.status='applied'
            ORDER BY l.created_at DESC
        """)
        rows = cur.fetchall()
        return success(rows)

    except Exception as e:
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()

@app.route("/api/manager/loan-decision", methods=["POST"])
def manager_loan_decision():
    d = request.json or {}

    loan_id = d.get("loan_id")
    decision = d.get("decision")

    if decision not in ["approved", "rejected"]:
        return error("Decision must be approved or rejected")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT l.loan_id, l.account_id, l.principal_amount,
                   l.status, a.balance
            FROM loans l
            JOIN accounts a ON l.account_id = a.account_id
            WHERE l.loan_id=%s
        """, (loan_id,))
        loan = cur.fetchone()

        if not loan:
            return error("Loan not found", 404)

        if decision == "rejected":
            cur.execute("""
                UPDATE loans
                SET status='rejected'
                WHERE loan_id=%s
            """, (loan_id,))
        else:
            principal = Decimal(str(loan["principal_amount"]))
            balance = Decimal(str(loan["balance"]))
            new_balance = balance + principal

            cur.execute("""
                UPDATE accounts
                SET balance=%s
                WHERE account_id=%s
            """, (new_balance, loan["account_id"]))

            cur.execute("""
                UPDATE loans
                SET status='active',
                    disbursed_on=%s,
                    approved_at=%s,
                    loan_clear_date=DATE_ADD(%s, INTERVAL tenure_months MONTH),
                    next_emi_date=DATE_ADD(%s, INTERVAL 1 MONTH)
                WHERE loan_id=%s
            """, (ist_today(), ist_now(), ist_today(), ist_today(), loan_id))

            txn_ref = insert_transaction(
                cur, loan["account_id"], "loan_credit", principal, new_balance,
                f"Loan amount credited for Loan #{loan_id}"
            )

        conn.commit()
        return success(msg=f"Loan {decision} successfully")

    except Exception as e:
        conn.rollback()
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()        

# ════════════════════════════════════════════════════════
#   FIXED DEPOSIT ROUTES
# ════════════════════════════════════════════════════════

def get_fd_interest_rate(tenure_months, cur=None):
    """
    FD interest rate based on tenure.
    First tries fd_rate_slabs table. If table is not available,
    uses fallback slabs.
    """
    tenure_months = int(tenure_months)

    if cur is not None:
        try:
            cur.execute("""
                SELECT interest_rate
                FROM fd_rate_slabs
                WHERE %s >= min_months
                  AND (max_months IS NULL OR %s <= max_months)
                ORDER BY min_months
                LIMIT 1
            """, (tenure_months, tenure_months))
            row = cur.fetchone()
            if row:
                return Decimal(str(row["interest_rate"]))
        except Exception:
            pass

    if tenure_months <= 6:
        return Decimal("4.50")
    elif tenure_months <= 12:
        return Decimal("5.50")
    elif tenure_months <= 24:
        return Decimal("6.25")
    elif tenure_months <= 36:
        return Decimal("6.75")
    elif tenure_months <= 60:
        return Decimal("7.25")
    else:
        return Decimal("7.50")


def calculate_fd_maturity(amount, rate, tenure_months):
    """
    Simple-interest FD calculation for DBMS project:
    maturity = amount + (amount * annual_rate * months / 1200)
    """
    amount = Decimal(str(amount))
    rate = Decimal(str(rate))
    tenure_months = Decimal(str(tenure_months))
    maturity = amount + ((amount * rate * tenure_months) / Decimal("1200"))
    return maturity.quantize(Decimal("0.01"))


@app.route("/api/fd/rate-preview", methods=["POST"])
def fd_rate_preview():
    d = request.json or {}

    try:
        amount = Decimal(str(d.get("amount", 0)))
        tenure = int(d.get("tenure_months", 0))

        if amount <= 0:
            return error("FD amount must be positive")
        if tenure <= 0:
            return error("Tenure must be positive")

        conn = get_db()
        cur = conn.cursor(dictionary=True)

        try:
            rate = get_fd_interest_rate(tenure, cur)
            maturity = calculate_fd_maturity(amount, rate, tenure)
            interest = (maturity - amount).quantize(Decimal("0.01"))

            return success({
                "amount": amount,
                "tenure_months": tenure,
                "interest_rate": rate,
                "maturity_amount": maturity,
                "interest_amount": interest
            }, "FD preview calculated")

        finally:
            cur.close()
            conn.close()

    except Exception as e:
        return error(str(e))


@app.route("/api/fd/apply", methods=["POST"])
def apply_fixed_deposit():
    """
    Customer applies for FD.
    Manager must approve before amount is locked/deducted.
    """
    d = request.json or {}

    customer_id = d.get("customer_id")
    account_number = d.get("account_number")
    amount = Decimal(str(d.get("amount", 0)))
    tenure = int(d.get("tenure_months", 0))

    if not customer_id:
        return error("Customer ID is required")
    if not account_number:
        return error("Account number is required")
    if amount <= 0:
        return error("FD amount must be positive")
    if tenure <= 0:
        return error("Tenure must be positive")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT account_id, balance, status
            FROM accounts
            WHERE account_number=%s AND customer_id=%s
            LIMIT 1
        """, (account_number, customer_id))
        acc = cur.fetchone()

        if not acc:
            return error("Invalid account", 404)
        if acc["status"] != "active":
            return error("Selected account is not active", 403)
        if Decimal(str(acc["balance"])) < amount:
            return error("Insufficient balance for fixed deposit")

        rate = get_fd_interest_rate(tenure, cur)
        maturity = calculate_fd_maturity(amount, rate, tenure)

        cur.execute("""
            INSERT INTO fixed_deposits
            (customer_id, account_id, principal_amount, tenure_months,
             interest_rate, maturity_amount, status, applied_at)
            VALUES (%s,%s,%s,%s,%s,%s,'applied',%s)
        """, (
            customer_id,
            acc["account_id"],
            amount,
            tenure,
            rate,
            maturity,
            ist_now()
        ))

        fd_id = cur.lastrowid
        conn.commit()

        return success({
            "fd_id": fd_id,
            "account_number": account_number,
            "principal_amount": amount,
            "tenure_months": tenure,
            "interest_rate": rate,
            "maturity_amount": maturity,
            "status": "applied"
        }, "Fixed deposit request submitted. Waiting for manager approval.")

    except Exception as e:
        conn.rollback()
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()


@app.route("/api/fds/<int:customer_id>", methods=["GET"])
def get_customer_fixed_deposits(customer_id):
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT fd.fd_id, fd.customer_id, fd.account_id, a.account_number,
                   fd.principal_amount, fd.tenure_months,
                   fd.interest_rate, fd.maturity_amount, fd.status,
                   fd.applied_at, fd.approved_at, fd.maturity_date
            FROM fixed_deposits fd
            JOIN accounts a ON fd.account_id = a.account_id
            WHERE fd.customer_id=%s
            ORDER BY fd.applied_at DESC
        """, (customer_id,))
        return success(cur.fetchall())

    except Exception as e:
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()


@app.route("/api/manager/pending-fd", methods=["GET"])
@app.route("/api/admin/pending-fd", methods=["GET"])
def pending_fixed_deposits():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT fd.fd_id, c.full_name, c.email, a.account_number,
                   fd.principal_amount, fd.tenure_months,
                   fd.interest_rate, fd.maturity_amount,
                   fd.status, fd.applied_at
            FROM fixed_deposits fd
            JOIN customers c ON fd.customer_id = c.customer_id
            JOIN accounts a ON fd.account_id = a.account_id
            WHERE fd.status='applied'
            ORDER BY fd.applied_at DESC
        """)
        return success(cur.fetchall())

    except Exception as e:
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()


@app.route("/api/manager/fd-decision", methods=["POST"])
def manager_fd_decision():
    """
    Manager approves/rejects FD.
    If approved:
    - deduct FD amount from customer account
    - mark FD approved
    - store FD debit transaction with unique transaction_ref
    """
    d = request.json or {}

    fd_id = d.get("fd_id")
    decision = d.get("decision")

    if decision not in ["approved", "rejected"]:
        return error("Decision must be approved or rejected")

    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT fd.fd_id, fd.account_id, fd.principal_amount,
                   fd.tenure_months, fd.status, a.balance
            FROM fixed_deposits fd
            JOIN accounts a ON fd.account_id = a.account_id
            WHERE fd.fd_id=%s
        """, (fd_id,))
        fd = cur.fetchone()

        if not fd:
            return error("FD request not found", 404)
        if fd["status"] != "applied":
            return error("FD request already processed")

        if decision == "rejected":
            cur.execute("""
                UPDATE fixed_deposits
                SET status='rejected'
                WHERE fd_id=%s
            """, (fd_id,))
            txn_ref = None

        else:
            amount = Decimal(str(fd["principal_amount"]))
            balance = Decimal(str(fd["balance"]))

            if balance < amount:
                return error("Insufficient balance at approval time")

            new_balance = balance - amount

            cur.execute("""
                UPDATE accounts
                SET balance=%s
                WHERE account_id=%s
            """, (new_balance, fd["account_id"]))

            cur.execute("""
                UPDATE fixed_deposits
                SET status='approved',
                    approved_at=%s,
                    maturity_date=DATE_ADD(%s, INTERVAL %s MONTH)
                WHERE fd_id=%s
            """, (ist_now(), ist_today(), fd["tenure_months"], fd_id))

            # Use fd_debit if your schema supports it. If not, change to 'withdrawal'.
            try:
                txn_ref = insert_transaction(
                    cur, fd["account_id"], "fd_debit", amount, new_balance,
                    f"Fixed Deposit created FD #{fd_id}"
                )
            except Exception as tx_err:
                if "Data truncated" in str(tx_err) or "Incorrect" in str(tx_err):
                    txn_ref = insert_transaction(
                        cur, fd["account_id"], "withdrawal", amount, new_balance,
                        f"Fixed Deposit created FD #{fd_id}"
                    )
                else:
                    raise

        conn.commit()
        return success({"transaction_ref": txn_ref}, f"Fixed deposit {decision}")

    except Exception as e:
        conn.rollback()
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()


# ════════════════════════════════════════════════════════
#   ADMIN ALL TRANSACTIONS ROUTE
# ════════════════════════════════════════════════════════

@app.route("/api/admin/all-transactions", methods=["GET"])
def admin_all_transactions():
    """
    Manager/Staff can see all customer transactions.
    Includes From/To customer names for transfers.
    """
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    try:
        cur.execute("""
            SELECT
                t.transaction_id,
                t.transaction_ref,
                c.full_name AS customer_name,
                c.email AS customer_email,
                a.account_number,
                t.transaction_type,
                t.amount,
                t.balance_after,
                t.description,
                t.reference_account,
                rc.full_name AS reference_customer_name,
                rc.email AS reference_customer_email,
                t.transfer_mode,
                t.status,
                t.created_at
            FROM transactions t
            JOIN accounts a ON t.account_id = a.account_id
            JOIN customers c ON a.customer_id = c.customer_id
            LEFT JOIN accounts ra ON t.reference_account = ra.account_number
            LEFT JOIN customers rc ON ra.customer_id = rc.customer_id
            ORDER BY t.created_at DESC
        """)

        return success(cur.fetchall())

    except Exception as e:
        return error(str(e), 500)

    finally:
        cur.close()
        conn.close()



# ════════════════════════════════════════════════════════
#   MANAGER / STAFF DASHBOARD SUMMARY ROUTES
# ════════════════════════════════════════════════════════

@app.route("/api/admin/summary", methods=["GET"])
def admin_summary():
    conn = get_db()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT COUNT(*) AS total_customers FROM customers")
    customers = cur.fetchone()["total_customers"]

    cur.execute("SELECT COUNT(*) AS total_accounts FROM accounts")
    accounts = cur.fetchone()["total_accounts"]

    cur.execute("SELECT COALESCE(SUM(balance), 0) AS total_balance FROM accounts WHERE status='active'")
    balance = cur.fetchone()["total_balance"]

    cur.execute("SELECT COUNT(*) AS total_tx FROM transactions WHERE DATE(created_at)=%s", (ist_today(),))
    today_tx = cur.fetchone()["total_tx"]

    cur.execute("SELECT COUNT(*) AS pending_customers FROM customers WHERE approval_status='pending'")
    pending_customers_count = cur.fetchone()["pending_customers"]

    cur.execute("SELECT COUNT(*) AS approved_customers FROM customers WHERE approval_status='approved'")
    approved_customers_count = cur.fetchone()["approved_customers"]

    cur.execute("SELECT COUNT(*) AS total_loans FROM loans")
    total_loans = cur.fetchone()["total_loans"]

    cur.execute("SELECT COUNT(*) AS pending_loans FROM loans WHERE status='applied'")
    pending_loans = cur.fetchone()["pending_loans"]

    try:
        cur.execute("SELECT COUNT(*) AS total_fd FROM fixed_deposits")
        total_fd = cur.fetchone()["total_fd"]
        cur.execute("SELECT COUNT(*) AS pending_fd FROM fixed_deposits WHERE status='applied'")
        pending_fd = cur.fetchone()["pending_fd"]
    except Exception:
        total_fd = 0
        pending_fd = 0

    cur.close()
    conn.close()

    return success({
        "total_customers": customers,
        "total_accounts": accounts,
        "total_balance": balance,
        "today_transactions": today_tx,
        "pending_customers": pending_customers_count,
        "approved_customers": approved_customers_count,
        "total_loans": total_loans,
        "pending_loans": pending_loans,
        "total_fd": total_fd,
        "pending_fd": pending_fd
    })


# ─── RUN ────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, port=5000)
