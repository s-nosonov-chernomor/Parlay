from app.db.session import SessionLocal
from app.db import auth_crud
from app.services.security import hash_password

def main():
    with SessionLocal() as db:
        if not auth_crud.get_user_by_username(db, "lite_nsa"):
            auth_crud.create_user(
                db,
                username="lite_nsa",
                password_hash=hash_password("qwe123"),
                role="admin",
            )
        # if not auth_crud.get_user_by_username(db, "viewer"):
        #     auth_crud.create_user(
        #         db,
        #         username="viewer",
        #         password_hash=hash_password("viewer123"),
        #         role="viewer",
        #     )
        db.commit()
        print("ok")

if __name__ == "__main__":
    main()