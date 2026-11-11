import csv
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class StudentsService:
    @classmethod
    def read_xlsx(cls, path: Path) -> list[dict]:
        """Reads students from an xlsx file without third-party dependencies."""
        with zipfile.ZipFile(str(path)) as z:
            strings = []
            if "xl/sharedStrings.xml" in z.namelist():
                tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in tree.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                    text = "".join(t.text for t in si.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t") if t.text)
                    strings.append(text)

            sheet_xml = "xl/worksheets/sheet1.xml"
            if sheet_xml not in z.namelist():
                return []

            tree = ET.fromstring(z.read(sheet_xml))
            raw_rows = []
            for row in tree.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                r_data = []
                for c in row.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                    v = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                    t = c.get("t")
                    val = v.text if v is not None else ""
                    if t == "s" and val.isdigit():
                        val = strings[int(val)]
                    r_data.append(val.strip())
                if r_data:
                    raw_rows.append(r_data)

            if not raw_rows:
                return []

            headers = [h.strip().lower() for h in raw_rows[0]]
            students = []
            for r in raw_rows[1:]:
                row_dict = {headers[i]: r[i] for i in range(min(len(headers), len(r)))}
                name, email = cls._extract_name_and_email(row_dict)
                if name and email and EMAIL_REGEX.match(email):
                    students.append({"name": name, "email": email})

            return students

    @staticmethod
    def _extract_name_and_email(row_dict: dict) -> tuple[str | None, str | None]:
        """Extracts name and email supporting various column names."""
        name = None
        email = None

        # Check for first name + last name
        first_name = row_dict.get("first name") or row_dict.get("firstname") or row_dict.get("פרטי") or row_dict.get("שם פרטי")
        last_name = row_dict.get("last name") or row_dict.get("lastname") or row_dict.get("משפחה") or row_dict.get("שם משפחה")
        if first_name or last_name:
            name = f"{first_name or ''} {last_name or ''}".strip()

        if not name:
            name = row_dict.get("name") or row_dict.get("student_name") or row_dict.get("שם") or row_dict.get("שם מלא")

        email = row_dict.get("email") or row_dict.get("mail") or row_dict.get("אימייל") or row_dict.get("דוא\"ל") or row_dict.get("דוא״ל")

        name = name.strip() if name else None
        email = email.strip().lower() if email else None
        return name, email

    @classmethod
    def validate_csv(cls, csv_path: str) -> tuple[bool, str, list[dict]]:
        """
        Validates that the file exists, is non-empty, and has valid student rows.
        Supports both .csv and .xlsx files.
        """
        path = Path(csv_path)
        if not path.is_file():
            # If path ends with .csv but an .xlsx exists in the same folder, try loading that
            xlsx_alt = path.parent / f"{path.stem}.xlsx"
            if xlsx_alt.is_file():
                path = xlsx_alt
            else:
                return False, f"קובץ רשימת הסטודנטים אינו קיים בנתיב: {csv_path}", []

        # If xlsx file
        if path.suffix.lower() == ".xlsx":
            try:
                students = cls.read_xlsx(path)
                if not students:
                    return False, "קובץ ה-Excel ריק מסטודנטים תקינים", []
                return True, "", students
            except Exception as e:
                return False, f"שגיאה בקריאת קובץ ה-Excel: {str(e)}", []

        # If csv file
        students = []
        try:
            with open(path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                headers = [h.strip().lower() for h in (reader.fieldnames or [])]
                
                # Check column compatibility
                has_name = "name" in headers or ("first name" in headers and "last name" in headers)
                has_email = "email" in headers or "mail" in headers
                if not has_name or not has_email:
                    return False, "קובץ ה-CSV חייב להכיל עמודות 'name' (או 'first name' ו-'last name') וכן 'email' (או 'mail')", []

                for row_idx, row in enumerate(reader, start=2):
                    norm_row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                    name, email = cls._extract_name_and_email(norm_row)

                    if not name or not email:
                        continue

                    if not EMAIL_REGEX.match(email):
                        return False, f"כתובת אימייל לא תקינה בשורה {row_idx}: {email}", []

                    students.append({"name": name, "email": email})

            if not students:
                return False, "קובץ ה-CSV ריק מסטודנטים תקינים", []

            return True, "", students
        except Exception as e:
            return False, f"שגיאה בקריאת קובץ ה-CSV: {str(e)}", []

    @classmethod
    def get_student_by_email(cls, csv_path: str, email: str) -> dict | None:
        """Finds student in CSV by email. Returns dict or None."""
        if not email:
            return None
        valid, _, students = cls.validate_csv(csv_path)
        if not valid:
            return None
        target = email.strip().lower()
        for s in students:
            if s["email"] == target:
                return s
        return None

    @classmethod
    def get_absent_students(cls, csv_path: str, attended_emails: set[str]) -> list[dict]:
        """Returns students from CSV who did not attend."""
        valid, _, students = cls.validate_csv(csv_path)
        if not valid:
            return []
        attended_norm = {e.strip().lower() for e in attended_emails if e}
        return [s for s in students if s["email"].lower() not in attended_norm]
