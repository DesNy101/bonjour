"""python -m app.create_admin  -- interactive creation of a Super Administrator."""
import getpass
from app.database import SessionLocal
from app import bootstrap
from app.models import User, Role
from app.security import hash_password, password_problem


def main():
    db = SessionLocal()
    bootstrap.sync_permissions_and_roles(db)
    bootstrap.seed_reference_data(db)
    db.commit()
    email = input("Admin email: ").strip().lower()
    name = input("Full name: ").strip() or "Administrator"
    pw = getpass.getpass("Password (min 8, letters + numbers): ")
    problem = password_problem(pw)
    if problem:
        raise SystemExit(problem)
    if db.query(User).filter(User.email == email).first():
        raise SystemExit("A user with that email already exists.")
    role = db.query(Role).filter(Role.key == "super_admin").one()
    db.add(User(email=email, full_name=name, password_hash=hash_password(pw), role_id=role.id, job_title="Owner"))
    db.commit()
    print("Super Administrator created.")


if __name__ == "__main__":
    main()
