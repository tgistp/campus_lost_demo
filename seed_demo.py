"""Create classroom sample items without replacing existing registrations."""
import os
import core

if __name__ == "__main__":
    os.environ["CAMPUS_ALLOW_DEMO"] = "1"
    core.init_db()
    from demo_data import add_examples
    count=add_examples()
    print("Additional sample items:",count)
    print("Registrant code: PNU-DEMO. Existing data and completion states were kept.")
