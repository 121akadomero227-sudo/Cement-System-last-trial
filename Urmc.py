import json
import os
import shutil
import hashlib
import secrets
from datetime import datetime

# ============================================================
# CEMENT TRUCK OFFLOADING & WORKER PAYMENT SYSTEM
# PRODUCTION VERSION FOR PYDROID 3 / STANDARD PYTHON
# ============================================================

APP_NAME = "CEMENT TRUCK OFFLOADING SYSTEM"

DATA_FILE = "cement_records_production.json"
BACKUP_FOLDER = "database_backups"
STATEMENT_FOLDER = "payment_statements"

PRICE_PER_BAG = 150

# First-run password.
# CHANGE IT FROM OPTION 10 AFTER INSTALLATION.
DEFAULT_PASSWORD = "SecurePassword123"

DB_VERSION = 2

# Automatic backups: one is taken before every save and when the app opens.
# Only the newest MAX_BACKUPS files are kept so storage never fills up.
MAX_BACKUPS = 60


def set_storage_dir(base):
    """Point the database, backups and statements at an app-private folder.

    Needed on Android, where the current working directory is read-only.
    """
    global DATA_FILE, BACKUP_FOLDER, STATEMENT_FOLDER
    os.makedirs(base, exist_ok=True)
    DATA_FILE = os.path.join(base, "cement_records_production.json")
    BACKUP_FOLDER = os.path.join(base, "database_backups")
    STATEMENT_FOLDER = os.path.join(base, "payment_statements")
    os.makedirs(BACKUP_FOLDER, exist_ok=True)
    os.makedirs(STATEMENT_FOLDER, exist_ok=True)


def _backup_files():
    """Backup files, oldest first (by modified time)."""
    try:
        files = [
            os.path.join(BACKUP_FOLDER, f)
            for f in os.listdir(BACKUP_FOLDER) if f.endswith(".json")
        ]
        return sorted(files, key=os.path.getmtime)
    except OSError:
        return []


def prune_backups():
    for old in _backup_files()[:-MAX_BACKUPS]:
        try:
            os.remove(old)
        except OSError:
            pass


def auto_backup(tag="AUTO"):
    """Copy the live database into the backup folder. Returns path or None."""
    try:
        if not os.path.exists(DATA_FILE):
            return None
        os.makedirs(BACKUP_FOLDER, exist_ok=True)
        path = os.path.join(
            BACKUP_FOLDER,
            f"cement_records_{tag}_"
            + datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f") + ".json"
        )
        shutil.copyfile(DATA_FILE, path)  # fresh timestamp
        prune_backups()
        return path
    except OSError:
        return None


def last_backup_text():
    files = _backup_files()
    if not files:
        return "No backup yet"
    t = os.path.getmtime(files[-1])
    return ("Last backup " + datetime.fromtimestamp(t).strftime(
        "%d/%m/%Y %H:%M") + f" ({len(files)} kept)")


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_date():
    return datetime.now().strftime("%d/%m/%Y")


def now_time():
    return datetime.now().strftime("%H:%M:%S")


def now_timestamp():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def money(amount):
    return f"Shs {int(amount):,}"


def pause():
    input("\nPress Enter to continue...")


def clean_name(name):
    return " ".join(name.strip().split()).title()


# ============================================================
# PASSWORD SECURITY
# ============================================================

def make_password_hash(password, salt=None):

    if salt is None:
        salt = secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120000
    ).hex()

    return salt, digest


def verify_password(password, salt, stored_hash):

    try:

        _, digest = make_password_hash(
            password,
            salt
        )

        return secrets.compare_digest(
            digest,
            stored_hash
        )

    except Exception:

        return False


# ============================================================
# DATABASE
# ============================================================

def new_database():

    salt, password_hash = make_password_hash(
        DEFAULT_PASSWORD
    )

    return {

        "db_version": DB_VERSION,

        "created_at":
            now_timestamp(),

        "next_record_number":
            1,

        "next_payment_number":
            1,

        "password_salt":
            salt,

        "password_hash":
            password_hash,

        "trucks":
            []
    }


def validate_database(data):

    if not isinstance(data, dict):
        return False

    if not isinstance(
        data.get("trucks"),
        list
    ):
        return False

    if not isinstance(
        data.get("next_record_number"),
        int
    ):
        return False

    if not isinstance(
        data.get("next_payment_number"),
        int
    ):
        return False

    if not data.get("password_salt"):
        return False

    if not data.get("password_hash"):
        return False

    for truck in data["trucks"]:

        if not isinstance(truck, dict):
            return False

        required = [
            "system_record_number",
            "actual_truck_number",
            "offloading_date",
            "bags",
            "workers",
            "finalized"
        ]

        if any(
            key not in truck
            for key in required
        ):
            return False

        if not isinstance(
            truck["bags"],
            int
        ):
            return False

        if truck["bags"] <= 0:
            return False

        if not isinstance(
            truck["workers"],
            list
        ):
            return False

        if not truck["workers"]:
            return False

    return True


def load_data():

    """
    IMPORTANT:

    If the production database is damaged,
    the system DOES NOT silently create an
    empty database.

    This protects real payment records.
    """

    if not os.path.exists(DATA_FILE):

        data = new_database()

        if not save_data(
            data,
            create_backup=False
        ):

            raise RuntimeError(
                "Could not create the production database."
            )

        return data

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

    except (
        OSError,
        json.JSONDecodeError
    ) as exc:

        raise RuntimeError(
            "The production database cannot be read. "
            "No data was changed. "
            "Restore a backup before continuing."
        ) from exc

    if not validate_database(data):

        raise RuntimeError(
            "The production database failed integrity checks. "
            "No data was changed. "
            "Restore a backup before continuing."
        )

    return data


def save_data(
    data,
    create_backup=True
):

    """
    Safely save the database.

    Existing database is backed up before replacement.
    """

    if not validate_database(data):

        print(
            "\nERROR: Database validation failed."
        )

        return False

    try:

        # ----------------------------------------------------
        # BACKUP OLD DATABASE
        # ----------------------------------------------------

        if (
            create_backup
            and os.path.exists(DATA_FILE)
        ):

            os.makedirs(
                BACKUP_FOLDER,
                exist_ok=True
            )

            backup_name = (
                "cement_records_backup_"
                + datetime.now().strftime(
                    "%Y-%m-%d_%H-%M-%S-%f"
                )
                + ".json"
            )

            backup_path = os.path.join(
                BACKUP_FOLDER,
                backup_name
            )

            shutil.copyfile(
                DATA_FILE,
                backup_path
            )

            prune_backups()

        # ----------------------------------------------------
        # WRITE TEMPORARY DATABASE
        # ----------------------------------------------------

        temp_file = DATA_FILE + ".tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )

            f.flush()

        # ----------------------------------------------------
        # REPLACE DATABASE
        # ----------------------------------------------------

        os.replace(
            temp_file,
            DATA_FILE
        )

        return True

    except OSError as exc:

        try:

            if os.path.exists(
                DATA_FILE + ".tmp"
            ):

                os.remove(
                    DATA_FILE + ".tmp"
                )

        except OSError:
            pass

        print(
            f"\nERROR: Database could not be saved: {exc}"
        )

        return False


# ============================================================
# PASSWORD LOGIN
# ============================================================

def check_password(data):

    print("=" * 72)

    print(
        APP_NAME
    )

    print(
        "PRODUCTION VERSION"
    )

    print("=" * 72)

    for attempt in range(1, 4):

        entered = input(
            "\nEnter administrator password: "
        )

        if verify_password(
            entered,
            data["password_salt"],
            data["password_hash"]
        ):

            print(
                "\nAccess Granted.\n"
            )

            return True

        remaining = 3 - attempt

        if remaining:

            print(
                f"Incorrect password. "
                f"{remaining} attempt(s) remaining."
            )

        else:

            print(
                "\nAccess Denied. "
                "Program exiting."
            )

    return False


# ============================================================
# CHANGE PASSWORD
# ============================================================

def change_password(data):

    print("\n" + "=" * 72)

    print(
        "CHANGE ADMINISTRATOR PASSWORD"
    )

    print("=" * 72)

    current = input(
        "\nEnter current password: "
    )

    if not verify_password(
        current,
        data["password_salt"],
        data["password_hash"]
    ):

        print(
            "\nIncorrect current password."
        )

        pause()
        return

    new_password = input(
        "Enter new password: "
    )

    if len(new_password) < 8:

        print(
            "\nPassword must contain at least "
            "8 characters."
        )

        pause()
        return

    confirm = input(
        "Confirm new password: "
    )

    if new_password != confirm:

        print(
            "\nPasswords do not match."
        )

        pause()
        return

    salt, password_hash = (
        make_password_hash(new_password)
    )

    old_salt = data["password_salt"]
    old_hash = data["password_hash"]

    data["password_salt"] = salt
    data["password_hash"] = password_hash

    if save_data(data):

        print(
            "\nPassword changed successfully."
        )

    else:

        data["password_salt"] = old_salt
        data["password_hash"] = old_hash

        print(
            "\nPassword was NOT changed "
            "because saving failed."
        )

    pause()


# ============================================================
# NUMBER GENERATION
# ============================================================

def get_next_record_number(data):

    number = data.get(
        "next_record_number",
        1
    )

    data["next_record_number"] = (
        number + 1
    )

    return number


def get_next_payment_id(data):

    number = data.get(
        "next_payment_number",
        1
    )

    date_part = datetime.now().strftime(
        "%Y%m%d"
    )

    time_part = datetime.now().strftime(
        "%H%M%S"
    )

    payment_id = (
        f"PAY-{date_part}-"
        f"{time_part}-"
        f"{number:03d}"
    )

    data["next_payment_number"] = (
        number + 1
    )

    return payment_id


# ============================================================
# TRUCK CALCULATIONS
# ============================================================

def truck_price(truck):

    try:
        price = float(truck.get("price_per_bag", PRICE_PER_BAG))
    except (TypeError, ValueError):
        price = float(PRICE_PER_BAG)
    return price


def truck_revenue(truck):

    # Uses the price saved on the record, so changing the system price
    # never rewrites old trucks or their receipts.
    return int(round(truck["bags"] * truck_price(truck)))


def worker_shares(
    total_money,
    worker_count
):

    if worker_count <= 0:
        return []

    base = (
        total_money
        // worker_count
    )

    remainder = (
        total_money
        % worker_count
    )

    shares = []

    for i in range(worker_count):

        if i < remainder:

            shares.append(
                base + 1
            )

        else:

            shares.append(
                base
            )

    return shares


def unpaid_trucks(data):

    return [
        truck
        for truck in data["trucks"]
        if not truck.get(
            "finalized",
            False
        )
    ]


def paid_trucks(data):

    return [
        truck
        for truck in data["trucks"]
        if truck.get(
            "finalized",
            False
        )
    ]


# ============================================================
# ACTUAL TRUCK NUMBER CHECK
# ============================================================

def actual_truck_exists(
    data,
    actual_number
):

    target = (
        actual_number
        .strip()
        .upper()
    )

    for truck in data["trucks"]:

        existing = str(
            truck.get(
                "actual_truck_number",
                ""
            )
        ).strip().upper()

        if existing == target:

            return truck

    return None


# ============================================================
# DATE INPUT
# ============================================================

def get_offloading_date():

    while True:

        value = input(
            "\nEnter actual offloading date "
            "(DD/MM/YYYY)"
            " [Enter = today]: "
        ).strip()

        if not value:

            return now_date()

        try:

            datetime.strptime(
                value,
                "%d/%m/%Y"
            )

            return value

        except ValueError:

            print(
                "Invalid date."
            )

            print(
                "Use DD/MM/YYYY."
            )


# ============================================================
# OPTION 1
# RECORD NEW TRUCK
# ============================================================

def record_truck(data):

    print("\n" + "=" * 72)

    print(
        "RECORD NEW TRUCK"
    )

    print("=" * 72)

    # --------------------------------------------------------
    # ACTUAL TRUCK NUMBER
    # --------------------------------------------------------

    actual_number = input(
        "\nEnter actual truck number / registration: "
    ).strip()

    if not actual_number:

        print(
            "\nTruck number cannot be empty."
        )

        pause()
        return

    actual_number = (
        " ".join(
            actual_number.split()
        )
    )

    # --------------------------------------------------------
    # DUPLICATE CHECK
    # --------------------------------------------------------

    existing = actual_truck_exists(
        data,
        actual_number
    )

    if existing:

        print(
            "\nWARNING: This truck number "
            "already exists."
        )

        print(
            f"System Record #: "
            f"{existing['system_record_number']}"
        )

        print(
            f"Actual Truck #:  "
            f"{existing['actual_truck_number']}"
        )

        print(
            f"Offloading Date: "
            f"{existing['offloading_date']}"
        )

        print(
            f"Status: "
            f"{'PAID' if existing.get('finalized') else 'UNPAID'}"
        )

        confirm_duplicate = input(
            "\nIs this genuinely another "
            "offloading by the same truck? "
            "(yes/no): "
        ).strip().lower()

        if confirm_duplicate != "yes":

            print(
                "\nRecord cancelled."
            )

            pause()
            return

    # --------------------------------------------------------
    # OFFLOADING DATE
    # --------------------------------------------------------

    offloading_date = (
        get_offloading_date()
    )

    # --------------------------------------------------------
    # CEMENT BAGS
    # --------------------------------------------------------

    while True:

        try:

            bags = int(
                input(
                    "\nEnter number of cement bags: "
                ).strip()
            )

            if bags <= 0:

                print(
                    "Bags must be greater than zero."
                )

                continue

            break

        except ValueError:

            print(
                "Enter a valid whole number."
            )

    revenue = (
        bags
        * PRICE_PER_BAG
    )

    # --------------------------------------------------------
    # WORKERS
    # --------------------------------------------------------

    print(
        "\nEnter every worker who actually "
        "offloaded this truck."
    )

    print(
        "Type 'done' when finished."
    )

    workers = []

    while True:

        name = input(
            "Worker Name: "
        ).strip()

        if name.lower() == "done":

            if not workers:

                print(
                    "At least one worker is required."
                )

                continue

            break

        if not name:
            continue

        name = clean_name(
            name
        )

        if name in workers:

            print(
                f"{name} is already listed."
            )

            continue

        workers.append(
            name
        )

    # --------------------------------------------------------
    # WORKER SHARES
    # --------------------------------------------------------

    shares = worker_shares(
        revenue,
        len(workers)
    )

    # --------------------------------------------------------
    # SYSTEM RECORD NUMBER
    # --------------------------------------------------------

    record_number = (
        get_next_record_number(data)
    )

    # --------------------------------------------------------
    # PREVIEW
    # --------------------------------------------------------

    print("\n" + "-" * 72)

    print(
        "TRUCK RECORD PREVIEW"
    )

    print("-" * 72)

    print(
        f"System Record #: {record_number}"
    )

    print(
        f"Actual Truck #:  {actual_number}"
    )

    print(
        f"Offloading Date: {offloading_date}"
    )

    print(
        f"Cement Bags:     {bags:,}"
    )

    print(
        f"Price Per Bag:   {money(PRICE_PER_BAG)}"
    )

    print(
        f"Truck Revenue:   {money(revenue)}"
    )

    print(
        "\nWorkers:"
    )

    for worker, share in zip(
        workers,
        shares
    ):

        print(
            f"  - {worker}: "
            f"{money(share)}"
        )

    print(
        "-" * 72
    )

    confirm = input(
        "\nType YES to save this truck record: "
    ).strip().lower()

    if confirm != "yes":

        data["next_record_number"] -= 1

        print(
            "\nRecord cancelled."
        )

        pause()
        return

    # --------------------------------------------------------
    # CREATE RECORD
    # --------------------------------------------------------

    truck = {

        "system_record_number":
            record_number,

        "actual_truck_number":
            actual_number,

        "offloading_date":
            offloading_date,

        "bags":
            bags,

        "workers":
            workers,

        "finalized":
            False,

        "created_at":
            now_timestamp()
    }

    data["trucks"].append(
        truck
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    if save_data(data):

        print(
            "\nTruck record saved successfully."
        )

        print(
            f"System Record #: "
            f"{record_number}"
        )

        print(
            f"Actual Truck #:  "
            f"{actual_number}"
        )

        print(
            f"Offloading Date: "
            f"{offloading_date}"
        )

    else:

        data["trucks"].pop()

        data["next_record_number"] -= 1

        print(
            "\nTruck record was NOT saved."
        )

    pause()


# ============================================================
# OPTION 2
# VIEW UNPAID BALANCES
# ============================================================

def view_unpaid_balances(data):

    trucks = sorted(
        unpaid_trucks(data),
        key=lambda x:
        x["system_record_number"]
    )

    print("\n" + "=" * 82)

    print(
        "CURRENT UNPAID BALANCES"
    )

    print("=" * 82)

    if not trucks:

        print(
            "\nNo unpaid truck records."
        )

        pause()
        return

    total = sum(
        truck_revenue(t)
        for t in trucks
    )

    print(
        f"\nUnpaid Trucks: "
        f"{len(trucks)}"
    )

    print(
        f"Total Unpaid Money: "
        f"{money(total)}"
    )

    # --------------------------------------------------------
    # WORKER TOTALS
    # --------------------------------------------------------

    balances = {}

    for truck in trucks:

        shares = worker_shares(
            truck_revenue(truck),
            len(truck["workers"])
        )

        for worker, share in zip(
            truck["workers"],
            shares
        ):

            balances[worker] = (
                balances.get(
                    worker,
                    0
                )
                + share
            )

    print(
        "\nMONEY CURRENTLY OWED "
        "TO EACH WORKER"
    )

    print(
        "-" * 82
    )

    for worker in sorted(
        balances
    ):

        print(
            f"{worker}: "
            f"{money(balances[worker])}"
        )

    # --------------------------------------------------------
    # TRUCKS
    # --------------------------------------------------------

    print(
        "\nUNPAID TRUCKS"
    )

    print(
        "-" * 82
    )

    for truck in trucks:

        print(
            f"\nSystem Record #: "
            f"{truck['system_record_number']}"
        )

        print(
            f"Actual Truck #:  "
            f"{truck['actual_truck_number']}"
        )

        print(
            f"Offloading Date: "
            f"{truck['offloading_date']}"
        )

        print(
            f"Cement Bags: "
            f"{truck['bags']:,}"
        )

        print(
            f"Truck Revenue: "
            f"{money(truck_revenue(truck))}"
        )

        print(
            f"Workers: "
            f"{', '.join(truck['workers'])}"
        )

        print(
            "-" * 82
        )

    pause()


# ============================================================
# BUILD PAYMENT RECEIPT
# ============================================================

def build_statement_text(
    to_finalize,
    payout_balances,
    payment_id,
    payment_date,
    payment_time,
    total_revenue
):

    lines = []

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    lines.append(
        "=" * 78
    )

    lines.append(
        "              CEMENT OFFLOADING PAYMENT RECEIPT"
    )

    lines.append(
        "=" * 78
    )

    lines.append("")

    lines.append(
        f"PAYMENT BATCH ID: {payment_id}"
    )

    lines.append(
        f"PAYMENT DATE:     {payment_date}"
    )

    lines.append(
        f"PAYMENT TIME:     {payment_time}"
    )

    lines.append("")

    lines.append(
        f"TRUCKS SETTLED:   {len(to_finalize)}"
    )

    lines.append(
        f"TOTAL DISBURSED:  {money(total_revenue)}"
    )

    lines.append("")

    lines.append(
        "=" * 78
    )

    lines.append(
        "DETAILED TRUCK RECORDS"
    )

    lines.append(
        "=" * 78
    )

    # --------------------------------------------------------
    # TRUCK DETAILS
    # --------------------------------------------------------

    for truck in to_finalize:

        revenue = truck_revenue(
            truck
        )

        shares = worker_shares(
            revenue,
            len(truck["workers"])
        )

        lines.append("")

        lines.append(
            f"SYSTEM RECORD #:  "
            f"{truck['system_record_number']}"
        )

        lines.append(
            f"ACTUAL TRUCK #:   "
            f"{truck['actual_truck_number']}"
        )

        lines.append(
            f"OFFLOADING DATE:  "
            f"{truck['offloading_date']}"
        )

        lines.append(
            f"CEMENT BAGS:      "
            f"{truck['bags']:,}"
        )

        lines.append(
            f"PRICE PER BAG:    "
            f"{money(truck_price(truck))}"
        )

        lines.append(
            f"TRUCK REVENUE:    "
            f"{money(revenue)}"
        )

        lines.append("")

        lines.append(
            "WORKERS WHO OFFLOADED THIS TRUCK:"
        )

        for worker, share in zip(
            truck["workers"],
            shares
        ):

            lines.append(
                f"   - {worker}: "
                f"{money(share)}"
            )

        lines.append(
            "-" * 78
        )

    # --------------------------------------------------------
    # WORKER SUMMARY
    # --------------------------------------------------------

    lines.append("")

    lines.append(
        "WORKER PAYMENT SUMMARY"
    )

    lines.append(
        "=" * 78
    )

    for worker in sorted(
        payout_balances
    ):

        lines.append(
            f"{worker}: "
            f"{money(payout_balances[worker])}"
        )

    lines.append(
        "=" * 78
    )

    lines.append(
        f"TOTAL PAID TO WORKERS: "
        f"{money(sum(payout_balances.values()))}"
    )

    lines.append(
        "=" * 78
    )

    lines.append("")

    lines.append(
        "This receipt was automatically generated "
        "by the Cement Truck Offloading System."
    )

    lines.append(
        f"Receipt Generated: "
        f"{payment_date} {payment_time}"
    )

    return "\n".join(
        lines
    )


# ============================================================
# SAVE PAYMENT STATEMENT
# ============================================================

def save_statement(
    statement_text,
    payment_id
):

    try:

        os.makedirs(
            STATEMENT_FOLDER,
            exist_ok=True
        )

        filename = (
            f"{payment_id}"
            "_Payment_Statement.txt"
        )

        path = os.path.join(
            STATEMENT_FOLDER,
            filename
        )

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                statement_text
            )

        return path

    except OSError as exc:

        print(
            f"\nERROR creating payment receipt: "
            f"{exc}"
        )

        return None


# ============================================================
# OPTION 3
# FINALIZE PAYMENTS
# ============================================================

def finalize_payment_records(data, selected):
    """Non-interactive GUI adapter using the same payment transaction rules."""
    selected = sorted(selected, key=lambda x: x["system_record_number"])
    if not selected:
        return False
    unpaid_ids = {t["system_record_number"] for t in unpaid_trucks(data)}
    if any(t["system_record_number"] not in unpaid_ids for t in selected):
        raise RuntimeError("One or more selected trucks are no longer unpaid.")

    total = sum(truck_revenue(t) for t in selected)
    payout_balances = {}
    for truck in selected:
        shares = worker_shares(truck_revenue(truck), len(truck["workers"]))
        for worker, share in zip(truck["workers"], shares):
            payout_balances[worker] = payout_balances.get(worker, 0) + share

    payment_id = get_next_payment_id(data)
    payment_date = now_date()
    payment_time = now_time()
    statement_text = build_statement_text(
        selected, payout_balances, payment_id, payment_date,
        payment_time, total
    )
    statement_path = save_statement(statement_text, payment_id)
    if not statement_path:
        data["next_payment_number"] -= 1
        raise RuntimeError("Payment receipt could not be created.")

    originals = []
    for truck in selected:
        originals.append((truck, truck.get("finalized", False),
                          truck.get("payment_batch_id"), truck.get("payment_date"),
                          truck.get("payment_time"), truck.get("payment_timestamp")))
        truck["finalized"] = True
        truck["payment_batch_id"] = payment_id
        truck["payment_date"] = payment_date
        truck["payment_time"] = payment_time
        truck["payment_timestamp"] = f"{payment_date} {payment_time}"

    if not save_data(data):
        for truck, finalized, old_batch, old_date, old_time, old_timestamp in originals:
            truck["finalized"] = finalized
            for key, old in (("payment_batch_id", old_batch), ("payment_date", old_date),
                             ("payment_time", old_time), ("payment_timestamp", old_timestamp)):
                if old is None:
                    truck.pop(key, None)
                else:
                    truck[key] = old
        data["next_payment_number"] -= 1
        raise RuntimeError("Database save failed; no payment was safely finalized.")
    return payment_id


def finalize_payments(data):

    trucks = sorted(
        unpaid_trucks(data),
        key=lambda x:
        x["system_record_number"]
    )

    print("\n" + "=" * 84)

    print(
        "FINALIZE PAYMENTS"
    )

    print("=" * 84)

    if not trucks:

        print(
            "\nNo unpaid trucks available."
        )

        pause()
        return

    print(
        f"\nThere are "
        f"{len(trucks)} "
        f"unpaid truck(s)."
    )

    # --------------------------------------------------------
    # SHOW UNPAID TRUCKS
    # --------------------------------------------------------

    for index, truck in enumerate(
        trucks,
        start=1
    ):

        print(
            f"\n[{index}]"
        )

        print(
            f"  System Record #: "
            f"{truck['system_record_number']}"
        )

        print(
            f"  Actual Truck #:  "
            f"{truck['actual_truck_number']}"
        )

        print(
            f"  Offloading Date: "
            f"{truck['offloading_date']}"
        )

        print(
            f"  Bags: "
            f"{truck['bags']:,}"
        )

        print(
            f"  Truck Revenue: "
            f"{money(truck_revenue(truck))}"
        )

        print(
            f"  Workers: "
            f"{', '.join(truck['workers'])}"
        )

    # --------------------------------------------------------
    # HOW MANY?
    # --------------------------------------------------------

    while True:

        try:

            count = int(
                input(
                    "\nHow many oldest trucks "
                    "should be paid? "
                ).strip()
            )

            if count <= 0:

                print(
                    "Enter a number greater than zero."
                )

                continue

            if count > len(trucks):

                print(
                    f"Only {len(trucks)} "
                    "unpaid truck(s) are available."
                )

                continue

            break

        except ValueError:

            print(
                "Enter a valid whole number."
            )

    # --------------------------------------------------------
    # SELECT OLDEST
    # --------------------------------------------------------

    selected = trucks[:count]

    total = sum(
        truck_revenue(t)
        for t in selected
    )

    # --------------------------------------------------------
    # WORKER PAYOUTS
    # --------------------------------------------------------

    payout_balances = {}

    for truck in selected:

        shares = worker_shares(
            truck_revenue(truck),
            len(truck["workers"])
        )

        for worker, share in zip(
            truck["workers"],
            shares
        ):

            payout_balances[worker] = (
                payout_balances.get(
                    worker,
                    0
                )
                + share
            )

    # --------------------------------------------------------
    # CONFIRMATION SCREEN
    # --------------------------------------------------------

    print("\n" + "=" * 84)

    print(
        "PAYMENT CONFIRMATION"
    )

    print("=" * 84)

    for truck in selected:

        print(
            f"\nRecord #{truck['system_record_number']}"
        )

        print(
            f"Actual Truck #: "
            f"{truck['actual_truck_number']}"
        )

        print(
            f"Offloading Date: "
            f"{truck['offloading_date']}"
        )

        print(
            f"Bags: "
            f"{truck['bags']:,}"
        )

        print(
            f"Truck Revenue: "
            f"{money(truck_revenue(truck))}"
        )

        print(
            f"Workers: "
            f"{', '.join(truck['workers'])}"
        )

    print(
        "\n" + "-" * 84
    )

    print(
        f"TOTAL MONEY TO PAY: "
        f"{money(total)}"
    )

    print(
        "\nWORKER TOTALS:"
    )

    for worker in sorted(
        payout_balances
    ):

        print(
            f"  {worker}: "
            f"{money(payout_balances[worker])}"
        )

    print(
        "-" * 84
    )

    # --------------------------------------------------------
    # FIRST CONFIRMATION
    # --------------------------------------------------------

    confirm1 = input(
        "\nType YES to confirm that "
        "the trucks, workers and amounts "
        "have been checked: "
    ).strip().lower()

    if confirm1 != "yes":

        print(
            "\nPayment cancelled."
        )

        print(
            "No records changed."
        )

        pause()
        return

    # --------------------------------------------------------
    # SECOND CONFIRMATION
    # --------------------------------------------------------

    confirm2 = input(
        "\nType PAY to permanently mark "
        "these trucks as PAID: "
    ).strip().lower()

    if confirm2 != "pay":

        print(
            "\nPayment cancelled."
        )

        print(
            "No records changed."
        )

        pause()
        return

    # --------------------------------------------------------
    # PAYMENT ID
    # --------------------------------------------------------

    payment_id = get_next_payment_id(
        data
    )

    payment_date = now_date()

    payment_time = now_time()

    # --------------------------------------------------------
    # CREATE RECEIPT
    # --------------------------------------------------------

    statement_text = build_statement_text(
        selected,
        payout_balances,
        payment_id,
        payment_date,
        payment_time,
        total
    )

    statement_path = save_statement(
        statement_text,
        payment_id
    )

    if not statement_path:

        data["next_payment_number"] -= 1

        print(
            "\nPAYMENT STOPPED."
        )

        print(
            "The payment receipt could not "
            "be created."
        )

        print(
            "No truck was marked as paid."
        )

        pause()
        return

    # --------------------------------------------------------
    # KEEP ORIGINAL VALUES
    # --------------------------------------------------------

    originals = []

    for truck in selected:

        originals.append(
            (
                truck,
                truck.get(
                    "finalized",
                    False
                ),
                truck.get(
                    "payment_batch_id"
                ),
                truck.get(
                    "payment_date"
                ),
                truck.get(
                    "payment_time"
                ),
                truck.get(
                    "payment_timestamp"
                )
            )
        )

        # ----------------------------------------------------
        # MARK PAID
        # ----------------------------------------------------

        truck["finalized"] = True

        truck["payment_batch_id"] = (
            payment_id
        )

        truck["payment_date"] = (
            payment_date
        )

        truck["payment_time"] = (
            payment_time
        )

        truck["payment_timestamp"] = (
            f"{payment_date} "
            f"{payment_time}"
        )

    # --------------------------------------------------------
    # SAVE DATABASE
    # --------------------------------------------------------

    if not save_data(data):

        # Restore memory values.
        for (
            truck,
            finalized,
            old_batch,
            old_date,
            old_time,
            old_timestamp
        ) in originals:

            truck["finalized"] = (
                finalized
            )

            if old_batch is None:

                truck.pop(
                    "payment_batch_id",
                    None
                )

            else:

                truck["payment_batch_id"] = (
                    old_batch
                )

            if old_date is None:

                truck.pop(
                    "payment_date",
                    None
                )

            else:

                truck["payment_date"] = (
                    old_date
                )

            if old_time is None:

                truck.pop(
                    "payment_time",
                    None
                )

            else:

                truck["payment_time"] = (
                    old_time
                )

            if old_timestamp is None:

                truck.pop(
                    "payment_timestamp",
                    None
                )

            else:

                truck["payment_timestamp"] = (
                    old_timestamp
                )

        data["next_payment_number"] -= 1

        print(
            "\nCRITICAL: Database save failed."
        )

        print(
            "The trucks were NOT safely marked as paid."
        )

        print(
            "Do NOT pay again until the database "
            "has been checked."
        )

        pause()
        return

    # --------------------------------------------------------
    # SUCCESS REPORT
    # --------------------------------------------------------

    print("\n" + "=" * 84)

    print(
        "PAYMENT SUCCESSFULLY FINALIZED"
    )

    print("=" * 84)

    print(
        f"\nPayment Batch ID: "
        f"{payment_id}"
    )

    print(
        f"Payment Date:     "
        f"{payment_date}"
    )

    print(
        f"Payment Time:     "
        f"{payment_time}"
    )

    print(
        f"Trucks Settled:   "
        f"{len(selected)}"
    )

    print(
        f"Total Disbursed:  "
        f"{money(total)}"
    )

    print(
        "\nWORKER PAYMENTS:"
    )

    for worker in sorted(
        payout_balances
    ):

        print(
            f"  {worker}: "
            f"{money(payout_balances[worker])}"
        )

    print(
        "\nPayment Receipt:"
    )

    print(
        statement_path
    )

    pause()


# ============================================================
# OPTION 4
# PAYMENT HISTORY
# ============================================================

def view_payment_history(data):

    trucks = sorted(
        paid_trucks(data),
        key=lambda x:
        x["system_record_number"]
    )

    print("\n" + "=" * 84)

    print(
        "PAYMENT HISTORY"
    )

    print("=" * 84)

    if not trucks:

        print(
            "\nNo payment history."
        )

        pause()
        return

    total = sum(
        truck_revenue(t)
        for t in trucks
    )

    print(
        f"\nPaid Truck Records: "
        f"{len(trucks)}"
    )

    print(
        f"Total Revenue Paid: "
        f"{money(total)}"
    )

    for truck in trucks:

        print(
            "\n" + "-" * 84
        )

        print(
            f"System Record #:  "
            f"{truck['system_record_number']}"
        )

        print(
            f"Actual Truck #:   "
            f"{truck['actual_truck_number']}"
        )

        print(
            f"Offloading Date:  "
            f"{truck['offloading_date']}"
        )

        print(
            f"Payment Batch ID: "
            f"{truck.get('payment_batch_id', 'N/A')}"
        )

        print(
            f"Payment Date:     "
            f"{truck.get('payment_date', 'N/A')}"
        )

        print(
            f"Payment Time:     "
            f"{truck.get('payment_time', 'N/A')}"
        )

        print(
            f"Cement Bags:      "
            f"{truck['bags']:,}"
        )

        print(
            f"Truck Revenue:    "
            f"{money(truck_revenue(truck))}"
        )

        print(
            f"Workers:          "
            f"{', '.join(truck['workers'])}"
        )

    print(
        "-" * 84
    )

    pause()


# ============================================================
# OPTION 5
# SEARCH ACTUAL TRUCK
# ============================================================

def search_truck(data):

    print("\n" + "=" * 72)

    print(
        "SEARCH ACTUAL TRUCK NUMBER"
    )

    print("=" * 72)

    query = input(
        "\nEnter actual truck number: "
    ).strip().upper()

    if not query:

        print(
            "\nSearch cancelled."
        )

        pause()
        return

    matches = []

    for truck in data["trucks"]:

        if query in (
            truck["actual_truck_number"]
            .upper()
        ):

            matches.append(
                truck
            )

    if not matches:

        print(
            "\nNo matching truck records found."
        )

        pause()
        return

    for truck in sorted(
        matches,
        key=lambda x:
        x["system_record_number"]
    ):

        print(
            "\n" + "-" * 72
        )

        print(
            f"System Record #:  "
            f"{truck['system_record_number']}"
        )

        print(
            f"Actual Truck #:   "
            f"{truck['actual_truck_number']}"
        )

        print(
            f"Offloading Date:  "
            f"{truck['offloading_date']}"
        )

        print(
            f"Cement Bags:      "
            f"{truck['bags']:,}"
        )

        print(
            f"Truck Revenue:    "
            f"{money(truck_revenue(truck))}"
        )

        print(
            f"Status:           "
            f"{'PAID' if truck.get('finalized') else 'UNPAID'}"
        )

        if truck.get("finalized"):

            print(
                f"Payment Batch ID: "
                f"{truck.get('payment_batch_id', 'N/A')}"
            )

            print(
                f"Payment Date:     "
                f"{truck.get('payment_date', 'N/A')}"
            )

        print(
            f"Workers:          "
            f"{', '.join(truck['workers'])}"
        )

    print(
        "-" * 72
    )

    pause()


# ============================================================
# OPTION 6
# WORKER EARNINGS HISTORY
# ============================================================

def worker_history(data):

    print("\n" + "=" * 76)

    print(
        "WORKER EARNINGS HISTORY"
    )

    print("=" * 76)

    name = input(
        "\nEnter worker name: "
    ).strip()

    if not name:

        print(
            "\nSearch cancelled."
        )

        pause()
        return

    target = clean_name(
        name
    )

    total_paid = 0
    total_unpaid = 0

    records = []

    for truck in data["trucks"]:

        if target not in truck["workers"]:
            continue

        shares = worker_shares(
            truck_revenue(truck),
            len(truck["workers"])
        )

        position = truck["workers"].index(
            target
        )

        share = shares[position]

        records.append(
            (
                truck,
                share
            )
        )

        if truck.get("finalized"):

            total_paid += share

        else:

            total_unpaid += share

    if not records:

        print(
            f"\nNo records found for {target}."
        )

        pause()
        return

    print(
        f"\nWORKER: {target}"
    )

    print(
        f"Total Paid:   "
        f"{money(total_paid)}"
    )

    print(
        f"Total Unpaid: "
        f"{money(total_unpaid)}"
    )

    for truck, share in records:

        print(
            "\n" + "-" * 76
        )

        print(
            f"System Record #: "
            f"{truck['system_record_number']}"
        )

        print(
            f"Actual Truck #:  "
            f"{truck['actual_truck_number']}"
        )

        print(
            f"Offloading Date: "
            f"{truck['offloading_date']}"
        )

        print(
            f"Cement Bags: "
            f"{truck['bags']:,}"
        )

        print(
            f"Worker Share: "
            f"{money(share)}"
        )

        print(
            f"Status: "
            f"{'PAID' if truck.get('finalized') else 'UNPAID'}"
        )

        if truck.get("finalized"):

            print(
                f"Payment Batch: "
                f"{truck.get('payment_batch_id', 'N/A')}"
            )

    pause()


# ============================================================
# OPTION 7
# SYSTEM SUMMARY
# ============================================================

def system_summary(data):

    all_trucks = data["trucks"]

    unpaid = unpaid_trucks(
        data
    )

    paid = paid_trucks(
        data
    )

    total_bags = sum(
        truck["bags"]
        for truck in all_trucks
    )

    total_value = sum(
        truck_revenue(truck)
        for truck in all_trucks
    )

    paid_value = sum(
        truck_revenue(truck)
        for truck in paid
    )

    unpaid_value = sum(
        truck_revenue(truck)
        for truck in unpaid
    )

    print("\n" + "=" * 72)

    print(
        "SYSTEM SUMMARY"
    )

    print("=" * 72)

    print(
        f"\nTotal Truck Records:      "
        f"{len(all_trucks)}"
    )

    print(
        f"Paid Truck Records:       "
        f"{len(paid)}"
    )

    print(
        f"Unpaid Truck Records:     "
        f"{len(unpaid)}"
    )

    print(
        f"Total Cement Bags:        "
        f"{total_bags:,}"
    )

    print(
        f"Total Recorded Value:     "
        f"{money(total_value)}"
    )

    print(
        f"Total Paid Value:         "
        f"{money(paid_value)}"
    )

    print(
        f"Total Currently Unpaid:   "
        f"{money(unpaid_value)}"
    )

    print(
        f"Price Per Cement Bag:     "
        f"{money(PRICE_PER_BAG)}"
    )

    print(
        "\nFiles:"
    )

    print(
        f"Database:                 "
        f"{DATA_FILE}"
    )

    print(
        f"Backups:                  "
        f"{BACKUP_FOLDER}"
    )

    print(
        f"Payment Statements:       "
        f"{STATEMENT_FOLDER}"
    )

    print(
        "=" * 72
    )

    pause()


# ============================================================
# OPTION 8
# VIEW PAYMENT STATEMENTS
# ============================================================

def list_statements():

    print("\n" + "=" * 76)

    print(
        "PAYMENT STATEMENTS"
    )

    print("=" * 76)

    if not os.path.exists(
        STATEMENT_FOLDER
    ):

        print(
            "\nNo payment statements found."
        )

        pause()
        return

    files = [
        name
        for name in os.listdir(
            STATEMENT_FOLDER
        )
        if name.lower().endswith(
            ".txt"
        )
    ]

    files.sort(
        reverse=True
    )

    if not files:

        print(
            "\nNo payment statements found."
        )

        pause()
        return

    for index, filename in enumerate(
        files,
        start=1
    ):

        print(
            f"{index}. {filename}"
        )

    while True:

        choice = input(
            "\nEnter statement number to open, "
            "or type 'back': "
        ).strip().lower()

        if choice == "back":
            return

        try:

            index = int(
                choice
            )

            if not 1 <= index <= len(files):

                print(
                    "Invalid selection."
                )

                continue

            path = os.path.join(
                STATEMENT_FOLDER,
                files[index - 1]
            )

            with open(
                path,
                "r",
                encoding="utf-8"
            ) as f:

                content = f.read()

            print(
                "\n" + "=" * 76
            )

            print(
                content
            )

            print(
                "=" * 76
            )

            pause()
            return

        except ValueError:

            print(
                "Enter a valid number."
            )

        except OSError as exc:

            print(
                f"Could not open statement: "
                f"{exc}"
            )

            pause()
            return


# ============================================================
# OPTION 9
# MANUAL DATABASE BACKUP
# ============================================================

def manual_backup():

    if not os.path.exists(
        DATA_FILE
    ):

        print(
            "\nNo database exists yet."
        )

        pause()
        return

    try:

        os.makedirs(
            BACKUP_FOLDER,
            exist_ok=True
        )

        filename = (
            "MANUAL_BACKUP_"
            + datetime.now().strftime(
                "%Y-%m-%d_%H-%M-%S-%f"
            )
            + ".json"
        )

        path = os.path.join(
            BACKUP_FOLDER,
            filename
        )

        shutil.copy2(
            DATA_FILE,
            path
        )

        print(
            "\nBackup created successfully:"
        )

        print(
            path
        )

    except OSError as exc:

        print(
            f"\nBackup failed: {exc}"
        )

    pause()


# ============================================================
# MAIN MENU
# ============================================================

def main_menu(data):

    while True:

        current_unpaid = (
            unpaid_trucks(data)
        )

        unpaid_count = len(
            current_unpaid
        )

        unpaid_money = sum(
            truck_revenue(t)
            for t in current_unpaid
        )

        print(
            "\n" + "=" * 76
        )

        print(
            APP_NAME
        )

        print(
            "PRODUCTION VERSION"
        )

        print(
            "=" * 76
        )

        print(
            f"CURRENT UNPAID TRUCKS: "
            f"{unpaid_count}"
        )

        print(
            f"CURRENT UNPAID MONEY:  "
            f"{money(unpaid_money)}"
        )

        print(
            "=" * 76
        )

        print(
            "1. Record New Truck"
        )

        print(
            "2. View Current Unpaid Balances"
        )

        print(
            "3. Finalize Payments"
        )

        print(
            "4. View Payment History"
        )

        print(
            "5. Search Actual Truck Number"
        )

        print(
            "6. Worker Earnings History"
        )

        print(
            "7. System Summary"
        )

        print(
            "8. View Payment Statements"
        )

        print(
            "9. Create Manual Database Backup"
        )

        print(
            "10. Change Administrator Password"
        )

        print(
            "11. Exit"
        )

        print(
            "=" * 76
        )

        choice = input(
            "\nSelect an option: "
        ).strip()

        if choice == "1":

            record_truck(
                data
            )

        elif choice == "2":

            view_unpaid_balances(
                data
            )

        elif choice == "3":

            finalize_payments(
                data
            )

        elif choice == "4":

            view_payment_history(
                data
            )

        elif choice == "5":

            search_truck(
                data
            )

        elif choice == "6":

            worker_history(
                data
            )

        elif choice == "7":

            system_summary(
                data
            )

        elif choice == "8":

            list_statements()

        elif choice == "9":

            manual_backup()

        elif choice == "10":

            change_password(
                data
            )

        elif choice == "11":

            print(
                "\nSystem closed safely."
            )

            break

        else:

            print(
                "\nInvalid option."
            )

            print(
                "Choose a number from 1 to 11."
            )


# ============================================================
# PROGRAM START
# ============================================================

def main():

    try:

        data = load_data()

    except RuntimeError as exc:

        print(
            "\n" + "=" * 72
        )

        print(
            "CRITICAL DATABASE ERROR"
        )

        print(
            "=" * 72
        )

        print(
            f"\n{exc}"
        )

        print(
            "\nProgram will NOT continue."
        )

        print(
            "This protects your real payment records."
        )

        print(
            "=" * 72
        )

        return

    if not check_password(
        data
    ):

        return

    main_menu(
        data
    )


# ============================================================
# RUN PROGRAM
# ============================================================

if __name__ == "__main__":

    main() 