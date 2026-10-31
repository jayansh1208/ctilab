"""Demonstrate MongoDB TLS, collection-scoped roles, and field redaction."""
from __future__ import annotations

import json
import os
from pathlib import Path

from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError, ServerSelectionTimeoutError

ROOT = Path(__file__).resolve().parents[1]
DB_NAME = "analytics"
CA_FILE = os.getenv("LAB12_TLS_CA_FILE", "/security/ca.crt")
CLIENT_FILE = os.getenv("LAB12_TLS_CLIENT_FILE", "/security/client.pem")
ADMIN_USER = os.getenv("LAB12_ADMIN_USERNAME", "labadmin")


def mongo_client(username: str, password: str, auth_source: str = DB_NAME, tls: bool = True):
    options = {
        "username": username,
        "password": password,
        "authSource": auth_source,
        "serverSelectionTimeoutMS": 5000,
    }
    if tls:
        options.update(tls=True, tlsCAFile=CA_FILE, tlsCertificateKeyFile=CLIENT_FILE)
    return MongoClient("mongodb://secure-mongo:27017/", **options)


def ensure_role(db, name: str, privileges: list[dict]) -> None:
    info = db.command("rolesInfo", name)
    if info.get("roles"):
        db.command("updateRole", name, privileges=privileges, roles=[])
    else:
        db.command("createRole", name, privileges=privileges, roles=[])


def ensure_user(db, name: str, password: str, roles: list[dict]) -> None:
    info = db.command("usersInfo", name)
    if info.get("users"):
        db.command("updateUser", name, pwd=password, roles=roles)
    else:
        db.command("createUser", name, pwd=password, roles=roles)


def expect_denied(action, label: str) -> None:
    try:
        action()
    except OperationFailure as exc:
        if exc.code != 13:
            raise
        print(f"PASS: {label} was denied (Unauthorized).")
        return
    raise AssertionError(f"Expected MongoDB to deny: {label}")


def check_plaintext_rejected() -> None:
    client = MongoClient(
        "mongodb://secure-mongo:27017/?directConnection=true",
        serverSelectionTimeoutMS=2500,
    )
    try:
        client.admin.command("ping")
    except PyMongoError:
        print("PASS: plaintext MongoDB connection was rejected.")
    else:
        raise AssertionError("A plaintext MongoDB connection unexpectedly succeeded.")
    finally:
        client.close()


def run_demo() -> dict:
    admin_password = os.environ["LAB12_ADMIN_PASSWORD"]
    read_password = os.environ["LAB12_READ_PASSWORD"]
    write_password = os.environ["LAB12_WRITE_PASSWORD"]
    hr_password = os.environ["LAB12_HR_PASSWORD"]

    check_plaintext_rejected()
    admin_client = mongo_client(ADMIN_USER, admin_password, auth_source="admin")
    try:
        admin_client.admin.command("ping")
        db = admin_client[DB_NAME]
        roles = [
            (
                "analyticsReader",
                [
                    {"resource": {"db": DB_NAME, "collection": "orders"}, "actions": ["find"]},
                    {"resource": {"db": DB_NAME, "collection": "employee_public"}, "actions": ["find"]},
                ],
            ),
            (
                "analyticsWriter",
                [{"resource": {"db": DB_NAME, "collection": "orders"}, "actions": ["find", "insert", "update", "remove"]}],
            ),
            (
                "hrReader",
                [{"resource": {"db": DB_NAME, "collection": "employees"}, "actions": ["find"]}],
            ),
        ]
        for role, privileges in roles:
            ensure_role(db, role, privileges)

        ensure_user(db, "app_user_read", read_password, [{"role": "analyticsReader", "db": DB_NAME}])
        ensure_user(db, "app_user_write", write_password, [{"role": "analyticsWriter", "db": DB_NAME}])
        ensure_user(db, "hr_user", hr_password, [{"role": "hrReader", "db": DB_NAME}])

        db.orders.delete_many({})
        db.orders.insert_many([
            {"order_id": "O-1001", "customer_id": "C-10", "status": "paid", "total": 58.50},
            {"order_id": "O-1002", "customer_id": "C-11", "status": "pending", "total": 24.00},
        ])
        db.employees.delete_many({})
        db.employees.insert_one({
            "employee_id": "E-001", "name": "Example Analyst", "department": "Security", "salary": 120000,
        })
        if "employee_public" in db.list_collection_names():
            db.drop_collection("employee_public")
        db.create_collection(
            "employee_public",
            viewOn="employees",
            pipeline=[{"$project": {"_id": 0, "employee_id": 1, "name": 1, "department": 1}}],
        )

        reader = mongo_client("app_user_read", read_password)
        try:
            reader_db = reader[DB_NAME]
            order_count = len(list(reader_db.orders.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])))
            redacted = reader_db.employee_public.find_one({"employee_id": "E-001"})
            if redacted is None or "salary" in redacted:
                raise AssertionError("The employee view did not redact salary.")
            expect_denied(lambda: reader_db.orders.insert_one({"order_id": "DENIED"}), "reader insert on orders")
            expect_denied(lambda: reader_db.employees.find_one({}), "reader access to employees")
        finally:
            reader.close()

        writer = mongo_client("app_user_write", write_password)
        try:
            writer_db = writer[DB_NAME]
            writer_db.orders.delete_many({"order_id": "O-RBAC-CHECK"})
            writer_db.orders.insert_one({"order_id": "O-RBAC-CHECK", "status": "new"})
            writer_db.orders.update_one({"order_id": "O-RBAC-CHECK"}, {"$set": {"status": "checked"}})
            writer_db.orders.delete_one({"order_id": "O-RBAC-CHECK"})
            expect_denied(lambda: writer_db.employees.find_one({}), "writer access to employees")
        finally:
            writer.close()

        hr = mongo_client("hr_user", hr_password)
        try:
            employee = hr[DB_NAME].employees.find_one({"employee_id": "E-001"})
            if employee is None or employee.get("salary") != 120000:
                raise AssertionError("HR role should be able to read the underlying salary field.")
        finally:
            hr.close()

        result = {
            "tls": "required; server CA verified; PyMongo presents client certificate",
            "plaintext_connection": "rejected",
            "rbac": {
                "reader": "find and aggregate on orders; find on employee_public view",
                "writer": "find/insert/update/remove on orders only",
                "hr_user": "find on employees, including salary",
                "reader_aggregate_status_groups": order_count,
                "public_employee_fields": sorted(redacted.keys()),
                "salary_hidden_from_reader": "salary" not in redacted,
                "salary_visible_to_hr": employee["salary"],
            },
        }
    finally:
        admin_client.close()

    print(json.dumps(result, indent=2))
    output = ROOT / "docs" / "lab12-results.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved verification results to {output}")
    return result


if __name__ == "__main__":
    run_demo()
