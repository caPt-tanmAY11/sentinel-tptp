"""
data_generator/indian_names.py
─────────────────────────────────────────────────────────────────────────────
Indian banking identity generators: names, UPI VPAs, PAN numbers,
account numbers, loan account numbers, IFSC codes.

All generators are deterministic given a seed (passed to random.Random).
Nothing is hardcoded in the outputs — patterns follow actual Indian formats.
─────────────────────────────────────────────────────────────────────────────
"""

import random
import re
import string
from datetime import date, timedelta
from typing import Optional


# ── First Names ──────────────────────────────────────────────────────────────

FIRST_NAMES_MALE = [
    "Aarav", "Aditya", "Ajay", "Akash", "Amit", "Anand", "Anil", "Ankit",
    "Anuj", "Arjun", "Arpit", "Arvind", "Ashish", "Ashok", "Avinash",
    "Deepak", "Dinesh", "Gaurav", "Girish", "Harsh", "Hemant", "Hitesh",
    "Jayesh", "Kiran", "Krishna", "Kunal", "Manoj", "Mohit", "Naveen",
    "Nikhil", "Nitin", "Pankaj", "Pradeep", "Pranav", "Prasad", "Praveen",
    "Rahul", "Rajesh", "Rakesh", "Ram", "Ramesh", "Ravi", "Rohit", "Sachin",
    "Sanjay", "Sanjeev", "Santosh", "Satyam", "Shiv", "Shivam", "Shyam",
    "Siddharth", "Sudhir", "Suresh", "Sunil", "Tarun", "Umesh", "Vijay",
    "Vikram", "Vikas", "Vinay", "Vinod", "Vishal", "Vivek", "Yash",
    "Alok", "Amitabh", "Atul", "Bhushan", "Dilip", "Girish", "Gopal",
    "Harish", "Jagdish", "Mahesh", "Mukesh", "Naresh", "Paresh", "Ritesh",
    "Rupesh", "Saurabh", "Sharad", "Shirish", "Suhas", "Sumit", "Umang",
    "Vaibhav", "Vipul", "Yadav", "Yogesh", "Zeeshan",
]

FIRST_NAMES_FEMALE = [
    "Aarti", "Aditi", "Aishwarya", "Ananya", "Anjali", "Anuja", "Ankita",
    "Archana", "Aruna", "Asha", "Bhavna", "Chitra", "Deepa", "Deepika",
    "Divya", "Gayatri", "Geeta", "Heena", "Ishita", "Jyoti", "Kavita",
    "Kiran", "Komal", "Laxmi", "Madhuri", "Manisha", "Meena", "Meera",
    "Megha", "Minal", "Namrata", "Nandita", "Neha", "Nisha", "Pallavi",
    "Pooja", "Prachi", "Pragya", "Priti", "Priya", "Rashmi", "Rekha",
    "Renu", "Ritu", "Rohini", "Rutuja", "Sadhana", "Sangeeta", "Sapna",
    "Seema", "Shilpa", "Shreya", "Shruti", "Sneha", "Sonali", "Sonal",
    "Sonam", "Suchitra", "Sunita", "Swati", "Tanvi", "Usha", "Varsha",
    "Vidya", "Vrinda", "Yogita", "Zainab",
    "Amrita", "Bhavana", "Chandani", "Disha", "Ekta", "Gargi", "Harsha",
    "Indira", "Jayshree", "Kamla", "Latika", "Mamta", "Nandini", "Omisha",
    "Poonam", "Radha", "Savita", "Taruna", "Uma", "Vijaya", "Yamini",
]

# ── Last Names by Region ──────────────────────────────────────────────────────

LAST_NAMES_NORTH = [
    "Sharma", "Gupta", "Agarwal", "Singh", "Verma", "Mishra", "Tiwari",
    "Pandey", "Srivastava", "Saxena", "Mathur", "Rastogi", "Bose",
    "Kumar", "Yadav", "Dubey", "Tripathi", "Shukla", "Joshi", "Bhatt",
    "Chauhan", "Rajput", "Thakur", "Rawat", "Bisht", "Negi", "Upadhyay",
]

LAST_NAMES_SOUTH = [
    "Nair", "Menon", "Pillai", "Iyer", "Iyengar", "Krishnan", "Raman",
    "Subramanian", "Venkatesh", "Naidu", "Reddy", "Rao", "Sharma",
    "Murthy", "Patel", "Shetty", "Kamath", "Bhat", "Hegde", "Pai",
    "Gowda", "Swamy", "Chettiar", "Mudaliar", "Pillai",
]

LAST_NAMES_WEST = [
    "Shah", "Mehta", "Desai", "Joshi", "Patil", "Kulkarni", "Deshpande",
    "Bhosale", "Jadhav", "Pawar", "More", "Shinde", "Kadam", "Mane",
    "Gaikwad", "Salvi", "Naik", "Raut", "Thakare", "Wagh", "Chavan",
]

LAST_NAMES_EAST = [
    "Chatterjee", "Banerjee", "Mukherjee", "Ghosh", "Das", "Roy",
    "Sen", "Bose", "Sarkar", "Biswas", "Chakraborty", "Dey",
    "Ganguly", "Mandal", "Saha", "Patra", "Mohapatra", "Behera",
]

LAST_NAMES_BY_REGION = {
    "Maharashtra": LAST_NAMES_WEST,
    "Gujarat": LAST_NAMES_WEST,
    "Karnataka": LAST_NAMES_SOUTH,
    "Tamil Nadu": LAST_NAMES_SOUTH,
    "Kerala": LAST_NAMES_SOUTH,
    "Telangana": LAST_NAMES_SOUTH,
    "Andhra Pradesh": LAST_NAMES_SOUTH,
    "West Bengal": LAST_NAMES_EAST,
    "Odisha": LAST_NAMES_EAST,
    "Jharkhand": LAST_NAMES_EAST,
    "Delhi": LAST_NAMES_NORTH,
    "Uttar Pradesh": LAST_NAMES_NORTH,
    "Madhya Pradesh": LAST_NAMES_NORTH,
    "Rajasthan": LAST_NAMES_NORTH,
    "Haryana": LAST_NAMES_NORTH,
    "Punjab": LAST_NAMES_NORTH,
    "Bihar": LAST_NAMES_NORTH,
    "Chhattisgarh": LAST_NAMES_NORTH,
    "Assam": LAST_NAMES_EAST,
    "Manipur": LAST_NAMES_EAST,
    "Meghalaya": LAST_NAMES_EAST,
    "Tripura": LAST_NAMES_EAST,
    "Nagaland": LAST_NAMES_EAST,
    "Mizoram": LAST_NAMES_EAST,
}


# ── UPI Bank Codes ────────────────────────────────────────────────────────────

UPI_BANK_CODES = [
    "sbi", "hdfcbank", "icicibank", "axisbank", "kotak",
    "ybl",          # Yes Bank / PhonePe
    "okaxis",       # Axis via Google Pay
    "okhdfcbank",   # HDFC via Google Pay
    "okicici",      # ICICI via Google Pay
    "oksbi",        # SBI via Google Pay
    "paytm",
    "ibl",          # IndusInd Bank
    "pnb",
    "boi",          # Bank of India
    "upi",          # generic
]

# Employer-specific payroll VPA patterns (used by transaction classifier)
PAYROLL_VPA_PATTERNS = {
    "TCS": "tcspayroll@neft",
    "Infosys": "infosys_payroll@neft",
    "Wipro": "wipropayroll@neft",
    "HCL Technologies": "hclpay@neft",
    "Tech Mahindra": "techmahindra_sal@neft",
    "Cognizant": "cognizant_payroll@neft",
    "HDFC Bank": "hdfchr@neft",
    "ICICI Bank": "icici_payroll@neft",
    "Bajaj Finance": "bajajfinance_sal@neft",
    "L&T": "landt_payroll@neft",
    "Tata Steel": "tatasteel_sal@neft",
    "Mahindra & Mahindra": "mahindra_hr@neft",
    "Reliance Industries": "rjio_payroll@neft",
    "Central Government": "cgg_salary@neft",
    "State Government": "stategov_sal@neft",
    "Indian Railways": "irctcpayroll@neft",
    "Apollo Hospitals": "apollohr@neft",
    "Fortis Healthcare": "fortis_payroll@neft",
    "IIT Delhi": "iitd_salary@neft",
    "Amity University": "amity_payroll@neft",
}


# ── Generator Functions ───────────────────────────────────────────────────────

def generate_first_name(gender: str, rng: Optional[random.Random] = None) -> str:
    """Generate a random Indian first name matching the given gender."""
    r = rng or random
    if gender == "Female":
        return r.choice(FIRST_NAMES_FEMALE)
    return r.choice(FIRST_NAMES_MALE)


def generate_last_name(state: str, rng: Optional[random.Random] = None) -> str:
    """Generate a region-appropriate last name for the given state."""
    r = rng or random
    pool = LAST_NAMES_BY_REGION.get(state, LAST_NAMES_NORTH)
    return r.choice(pool)


def generate_upi_vpa(
    first_name: str,
    last_name: str,
    rng: Optional[random.Random] = None,
) -> str:
    """
    Generate a realistic Indian UPI VPA.
    Format: firstname.lastname@bankcode  (with optional numeric suffix)

    Examples:
      rahul.sharma@sbi
      priya.menon95@hdfcbank
      ak.joshi@okaxis
    """
    r = rng or random
    bank = r.choice(UPI_BANK_CODES)

    # Normalise: lowercase, remove spaces, strip special chars
    first = re.sub(r"[^a-z]", "", first_name.lower())
    last  = re.sub(r"[^a-z]", "", last_name.lower())

    # Occasionally use only initials or abbreviated name
    style = r.randint(0, 4)
    if style == 0:
        handle = f"{first}.{last}"
    elif style == 1:
        handle = f"{first[0]}.{last}"
    elif style == 2:
        suffix = r.randint(1, 99)
        handle = f"{first}.{last}{suffix}"
    elif style == 3:
        suffix = r.randint(1980, 2000)
        handle = f"{first}{suffix}"
    else:
        handle = f"{first[0]}{last}"

    return f"{handle}@{bank}"


def generate_pan_number(
    first_name: str,
    rng: Optional[random.Random] = None,
) -> str:
    """
    Generate a valid-format PAN number.
    Format: AAAAA9999A  (5 letters, 4 digits, 1 letter)
    The 4th letter encodes taxpayer type; 5th is first char of surname.
    These are synthetic — not real PANs.
    """
    r = rng or random
    letters = string.ascii_uppercase
    first_three = "".join(r.choices(letters, k=3))
    taxpayer_type = r.choice(["P", "C", "H", "F", "A", "B", "G", "J", "L"])
    fifth = first_name[0].upper() if first_name else r.choice(letters)
    digits = "".join(r.choices(string.digits, k=4))
    last_letter = r.choice(letters)
    return f"{first_three}{taxpayer_type}{fifth}{digits}{last_letter}"


def generate_account_number(rng: Optional[random.Random] = None) -> str:
    """
    Generate a realistic Indian savings account number (11–16 digits).
    Follows the pattern of major Indian banks (no fixed length across banks).
    """
    r = rng or random
    length = r.choice([11, 12, 13, 14, 15, 16])
    # First digit is never 0 in Indian account numbers
    first = r.choice("123456789")
    rest = "".join(r.choices(string.digits, k=length - 1))
    return first + rest


def generate_loan_account_number(
    bank_code: str,
    loan_type: str,
    disbursement_year: int,
    sequence: int,
    rng: Optional[random.Random] = None,
) -> str:
    """
    Generate a loan account number.
    Format: BANK/TYPE/YEAR/SEQNO
    Examples:
      HDFC/PL/2022/00123456
      SBI/HL/2023/00098765
    """
    loan_type_codes = {
        "HOME":        "HL",
        "PERSONAL":    "PL",
        "AUTO":        "AL",
        "EDUCATION":   "EL",
        "BUSINESS":    "BL",
        "CREDIT_CARD": "CC",
    }
    code = loan_type_codes.get(loan_type.upper(), "XX")
    return f"{bank_code.upper()}/{code}/{disbursement_year}/{sequence:08d}"


def generate_ifsc_code(
    bank_code: str,
    rng: Optional[random.Random] = None,
) -> str:
    """
    Generate a valid-format IFSC code.
    Format: BBBB0NNNNNN  (4-char bank code, literal 0, 6-digit branch)
    Examples:
      HDFC0001234
      SBIN0056789
    """
    r = rng or random
    bank_ifsc_codes = {
        "HDFC Bank":      "HDFC",
        "ICICI Bank":     "ICIC",
        "SBI":            "SBIN",
        "Axis Bank":      "UTIB",
        "Kotak Mahindra": "KKBK",
        "Yes Bank":       "YESB",
        "IndusInd Bank":  "INDB",
        "PNB":            "PUNB",
        "Bank of India":  "BKID",
        "Canara Bank":    "CNRB",
    }
    # Attempt to match bank code; fall back to first 4 chars
    code = bank_ifsc_codes.get(bank_code, bank_code[:4].upper().ljust(4, "X"))
    branch = r.randint(1, 99999)
    return f"{code}0{branch:06d}"


def generate_nach_vpa(
    bank_code: str,
    loan_account_number: str,
) -> str:
    """
    Generate the NACH/ECS auto-debit VPA for a loan.
    Used by the transaction classifier to identify EMI debits.
    Example: HDFC_NACH_EMI_HDFC_PL_2022_00123456@nach
    """
    # Normalise loan account number — remove slashes
    loan_ref = loan_account_number.replace("/", "_")
    return f"{bank_code.upper()}_NACH_EMI_{loan_ref}@nach"


def generate_reference_number(
    platform: str,
    rng: Optional[random.Random] = None,
) -> str:
    """
    Generate a realistic payment reference number.
    - NEFT/RTGS: UTR format  HHHHDDDDDDDDDDDDDD  (18 chars)
    - UPI:       RRN format  DDDDDDDDDDDD         (12 digits)
    - NACH/ECS:  unique alphanumeric
    """
    r = rng or random
    platform = platform.upper()

    if platform in ("NEFT", "RTGS", "IMPS"):
        # UTR: 4-char bank code + date + sequence
        bank = "".join(r.choices(string.ascii_uppercase, k=4))
        date_str = str(r.randint(20230101, 20241231))
        seq = "".join(r.choices(string.digits, k=8))
        return f"{bank}{date_str}{seq}"[:22]

    elif platform == "UPI":
        # RRN: 12 digits
        return "".join(r.choices(string.digits, k=12))

    elif platform in ("NACH", "ECS"):
        # NACH reference
        return "NACH" + "".join(r.choices(string.digits + string.ascii_uppercase, k=12))

    else:
        return "REF" + "".join(r.choices(string.digits, k=10))


def get_payroll_vpa(employer_name: str) -> str:
    """Return the payroll VPA for a known employer, or generate a generic one."""
    if employer_name in PAYROLL_VPA_PATTERNS:
        return PAYROLL_VPA_PATTERNS[employer_name]
    # Generic: first 6 chars of employer name + payroll@neft
    slug = re.sub(r"[^a-z]", "", employer_name.lower())[:6]
    return f"{slug}_payroll@neft"