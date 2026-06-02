# Load the bbs messages from the database file to screen for admin functions
import pickle
import sqlite3

print("\n Hessenbot Database Admin Tool\n")


# load the bbs messages from the database file
try:
    with open('../data/bbsdb.pkl', 'rb') as f:
        bbs_messages = pickle.load(f)
except Exception as e:
    try:
        with open('data/bbsdb.pkl', 'rb') as f:
            bbs_messages = pickle.load(f)
    except Exception as e:
        bbs_messages = "System: data/bbsdb.pkl not found"

try:
    with open('../data/bbsdm.pkl', 'rb') as f:
        bbs_dm = pickle.load(f)
except Exception as e:
    try:
        with open('data/bbsdm.pkl', 'rb') as f:
            bbs_dm = pickle.load(f)
    except Exception as e:
        bbs_dm = "System: data/bbsdm.pkl not found"

try:
    with open('../data/email_db.pickle', 'rb') as f:
        email_db = pickle.load(f)
except Exception as e:
    try:
        with open('data/email_db.pickle', 'rb') as f:
            email_db = pickle.load(f)
    except Exception as e:
        email_db = "System: data/email_db.pickle not found"

try:
    with open('../data/sms_db.pickle', 'rb') as f:
        sms_db = pickle.load(f)
except Exception as e:
    try:
        with open('data/sms_db.pickle', 'rb') as f:
            sms_db = pickle.load(f)
    except Exception as e:
        sms_db = "System: data/sms_db.pickle not found"


# checklist.db admin display
print("\nCurrent Check-ins Table\n")

try:
    conn = sqlite3.connect('../data/checklist.db')
except Exception:
    conn = sqlite3.connect('data/checklist.db')
c = conn.cursor()
try:
    c.execute("""
        SELECT * FROM checkin
        WHERE removed = 0
        ORDER BY checkin_id DESC
        LIMIT 20
    """)
    rows = c.fetchall()
    col_names = [desc[0] for desc in c.description]
    if rows:
        header = " | ".join(f"{name:<15}" for name in col_names)
        print(header)
        print("-" * len(header))
        for row in rows:
            print(" | ".join(f"{str(col):<15}" for col in row))
    else:
        print("No check-ins found.")
except Exception as e:
    print(f"Error reading check-ins: {e}")
finally:
    conn.close()

# inventory.db admin display
print("\nCurrent Inventory Table\n")
try:
    conn = sqlite3.connect('../data/inventory.db')
except Exception:
    conn = sqlite3.connect('data/inventory.db')
c = conn.cursor()
try:
    c.execute("""
        SELECT * FROM inventory
        ORDER BY item_id DESC
        LIMIT 20
    """)
    rows = c.fetchall()
    col_names = [desc[0] for desc in c.description]
    if rows:
        header = " | ".join(f"{name:<15}" for name in col_names)
        print(header)
        print("-" * len(header))
        for row in rows:
            print(" | ".join(f"{str(col):<15}" for col in row))
    else:
        print("No inventory items found.")
except Exception as e:
    print(f"Error reading inventory: {e}")
finally:
    conn.close()


print("System: bbs_messages")
print(bbs_messages)
print("\nSystem: bbs_dm")
print(bbs_dm)
print("\nSystem: email_db")
print(email_db)
print("\nSystem: sms_db")
print(sms_db)
print("\n")
