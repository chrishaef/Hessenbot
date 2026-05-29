# SMTP module for the meshing-around bot
# 2024 Idea and code bits from https://github.com/tremmert81
# https://avtech.com/articles/138/list-of-email-to-sms-addresses/
# 2024 Kelly Keeton K7MHI

from modules.log import logger
from modules.settings import (
    SMTP_SERVER, SMTP_PORT, SMTP_AUTH, SMTP_USERNAME, SMTP_PASSWORD,
    FROM_EMAIL, EMAIL_SUBJECT, enableImap, IMAP_SERVER, IMAP_PORT,
    IMAP_USERNAME, IMAP_PASSWORD, IMAP_FOLDER, sysopEmails, bbs_ban_list
)
import pickle
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# System variables
trap_list_smtp = ("email:", "setemail", "sms:", "setsms", "clearsms")
smtpThrottle = {}
SMTP_TIMEOUT = 10

if enableImap:
    # Import IMAP library
    import imaplib
    import email

# Send email
def send_email(to_email, message, nodeID=0):
    global smtpThrottle
    
    # Clean up email address
    to_email = to_email.strip()
    
    # Basic email validation
    if "@" not in to_email or "." not in to_email:
        logger.warning(f"System: Invalid email address format: {to_email}")
        return False
        
    # throttle email to prevent abuse
    if to_email in smtpThrottle:
        if smtpThrottle[to_email] > time.time() - 120:
            logger.warning("System: Email throttled for " + to_email[:-6])
            return "⛔️Email throttled, try again later"
    smtpThrottle[to_email] = time.time()

    # check if email is in the ban list
    if nodeID in bbs_ban_list:
        logger.warning("System: Email blocked for " + str(nodeID))
        return "⛔️Email throttled, try again later"
    # Send email
    try:
        # Create message
        msg = MIMEMultipart()
        msg['From'] = FROM_EMAIL
        msg['To'] = to_email
        msg['Subject'] = EMAIL_SUBJECT
        msg.attach(MIMEText(message, 'plain'))

        # Connect to SMTP server
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=SMTP_TIMEOUT)
        try:
            # login /auth
            if SMTP_PORT == 587:
                server.starttls()
            if SMTP_AUTH:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
        except Exception as e:
            logger.warning(f"System: Failed to login to SMTP server: {str(e)}")
            return

        # Send email; this command will hold the program until the email is sent
        server.send_message(msg)
        server.quit()

        logger.info("System: Email sent to: " + to_email[:-6])
        return True
    except Exception as e:
        logger.warning(f"System: Failed to send email: {str(e)}")
        return False

def check_email(nodeID, sysop=False):
    if not enableImap:
        return

    try:
        # Connect to IMAP server
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT, timeout=SMTP_TIMEOUT)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select(IMAP_FOLDER)

        # Search for new emails
        status, data = mail.search(None, 'UNSEEN')
        if status == 'OK':
            for num in data[0].split():
                status, data = mail.fetch(num, '(RFC822)')
                if status == 'OK':
                    email_message = email.message_from_bytes(data[0][1])
                    email_from = email_message['from']
                    email_subject = email_message['subject']
                    email_body = ""

                    if not sysop:
                        # Check if email is whitelisted by particpant in the mesh
                        for address in sms_db[nodeID]:
                            if address in email_from:
                                email_body = email_message.get_payload()
                                logger.info("System: Email received from: " + email_from[:-6] + " for " + str(nodeID))
                                return email_body.strip()
                    else:
                        # Check if email is from sysop
                        for address in sysopEmails:
                            if address in email_from:
                                email_body = email_message.get_payload()
                                logger.info("System: SysOp Email received from: " + email_from[:-6] + " for sysop")
                                return email_body.strip()
                        
    except Exception as e:
        logger.warning("System: Failed to check email: " + str(e))
        return False

# initalize email db
email_db = {}
try:
    with open('data/email_db.pickle', 'rb') as f:
        email_db = pickle.load(f)
except:
    logger.warning("System: Email db not found, creating a new one")
    with open('data/email_db.pickle', 'wb') as f:
        pickle.dump(email_db, f)

def store_email(nodeID, email):
    global email_db

    # if not in db, add it
    logger.debug("System: Setting E-Mail for " + str(nodeID))
    email_db[nodeID] = email

    # save to a pickle for persistence, this is a simple db, be mindful of risk
    with open('data/email_db.pickle', 'wb') as f:
        pickle.dump(email_db, f)
    f.close()
    return True


# initalize SMS db
sms_db = [{'nodeID': 0, 'sms':[]}]
try:
    with open('data/sms_db.pickle', 'rb') as f:
        sms_db = pickle.load(f)
except:
    logger.warning("System: SMS db not found, creating a new one")
    with open('data/sms_db.pickle', 'wb') as f:
        pickle.dump(sms_db, f)

def store_sms(nodeID, sms):
    global sms_db
    try:
        logger.debug("System: Setting SMS for " + str(nodeID))
        # one address per node: update existing record, otherwise add a new one
        record = next((item for item in sms_db if item['nodeID'] == nodeID), None)
        if record is not None:
            record['sms'] = sms
        else:
            sms_db.append({'nodeID': nodeID, 'sms': sms})

        # save to a pickle for persistence, this is a simple db, be mindful of risk
        with open('data/sms_db.pickle', 'wb') as f:
            pickle.dump(sms_db, f)
        return True
    except Exception as e:
        logger.warning("System: Failed to store SMS: " + str(e))
        return False

def handle_sms(nodeID, message):
    global sms_db
    # if clearsms, remove all sms for node
    if message.lower().startswith("clearsms"):
        if any(item['nodeID'] == nodeID for item in sms_db):
            # remove record from db for nodeID
            sms_db = [item for item in sms_db if item['nodeID'] != nodeID]
            # update the pickle
            with open('data/sms_db.pickle', 'wb') as f:
                pickle.dump(sms_db, f)
            f.close()
            return "📲 address cleared"
        return "📲No address to clear"
    
    # send SMS to SMS in db. if none ask for one
    if message.lower().startswith("setsms"):
        parts = message.split(" ", 1)
        address = parts[1].strip() if len(parts) > 1 else ""
        if len(address) < 5:
            return "?📲setsms: example@phone.co"
        if "@" not in address or "." not in address:
            return "📲Please provide a valid email address"
        if store_sms(nodeID, address):
            return "📲SMS address set 📪"
        else:
            return "⛔️Failed to set address"
        
    if message.lower().startswith("sms:"):
        parts = message.split(" ", 1)
        body = parts[1].strip() if len(parts) > 1 else ""
        if not body:
            return "📲 Bitte Text angeben: sms: <Nachricht>"
        count = 0
        sent_any = False
        # for all dict items matching nodeID in sms_db send sms
        for item in sms_db:
            if item['nodeID'] == nodeID:
                sent_any = True
                smsEmail = item['sms']
                logger.info("System: Sending SMS for " + str(nodeID) + " to " + smsEmail)
                if send_email(smsEmail, body, nodeID):
                    count += 1
                else:
                    return "⛔️Failed to send SMS"
        if sent_any:
            return "📲SMS sent " + str(count) + " addresses 📤"
        else:
            return "📲No address set, use 📲setsms"
    
    return "Error: ⛔️ not understood. use:setsms example@phone.co"

def handle_email(nodeID, message):
    global email_db
    try:
        # send email to email in db. if none ask for one
        if message.lower().startswith("setemail"):
            message = message.split(" ", 1)
            if len(message) < 2:
                return "📧Please provide an email address"
            email_addr = message[1].strip()
            if "@" not in email_addr or "." not in email_addr:
                return "📧Please provide a valid email address"
            if store_email(nodeID, email_addr):
                return "📧Email address set 📪"
            return "Error: ⛔️ Failed to set email address"
            
        if message.lower().startswith("email:"):
            parts = message.split(" ", 1)
            if len(parts) < 2:
                return "Error: ⛔️ format should be: email: message  or, email: address@example.com #message"
                
            content = parts[1].strip()
            
            # Check if this is a direct email with address
            if "@" in content and "#" in content:
                # Split into email and message
                addr_msg = content.split("#", 1)
                if len(addr_msg) != 2:
                    return "Error: ⛔️ Message format should be: email: address@example.com #message"
                    
                to_email = addr_msg[0].strip()
                message_body = addr_msg[1].strip()
                
                logger.info(f"System: Sending email for {nodeID} to {to_email}")
                if send_email(to_email, message_body, nodeID): 
                    return "📧Email-sent 📤"
                return "⛔️Failed to send email"
                
            # Using stored email address
            elif nodeID in email_db:
                logger.info(f"System: Sending email for {nodeID} to stored address")
                if send_email(email_db[nodeID], content, nodeID):
                    return "📧Email-sent 📤"
                return "⛔️Failed to send email"
        
        return "Error: ⛔️ no email on file. use: setemail"
            
    except Exception as e:
        logger.error(f"System: Email handling error: {str(e)}")
        return "⛔️Failed to process email command"
