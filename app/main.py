import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal, ROUND_HALF_UP

from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, Field, EmailStr
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv

load_dotenv()

# --- DB Configuration ---
# ADDED tz_aware=True to fix the subtraction error
IST = timezone(timedelta(hours=5, minutes=30))
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True)
db = client[os.getenv("MONGO_DB", "attendance_db")]

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

@app.on_event("startup")
def startup_db():
    db.employees.create_index([("emp_code", ASCENDING)], unique=True)
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True)

# --- Rule Helpers ---

def round_half_up(n: float, decimals: int = 2) -> float:
    if n is None: return None
    return float(Decimal(str(n)).quantize(Decimal('1.' + '0' * decimals), rounding=ROUND_HALF_UP))

def to_ms(dt: Optional[datetime]) -> Optional[int]:
    if dt is None: return None
    return int(dt.timestamp() * 1000)

def from_ms(ms: int) -> datetime:
    # Ensure the created datetime is UTC Aware to match DB
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(microsecond=0)

def calculate_metrics(punch_in: datetime, punch_out: Optional[datetime], shift_start: str, shift_end: str, att_date: str):
    # Ensure both punch_in and punch_out are UTC aware for calculation
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)
    
    p_in_ist = punch_in.astimezone(IST)
    h_s, m_s = map(int, shift_start.split(":"))
    
    # R2 Late calculation
    start_time = datetime.fromisoformat(att_date).replace(hour=h_s, minute=m_s, tzinfo=IST)
    diff = (p_in_ist - start_time).total_seconds()
    late_min = int(diff // 60) if diff > 600 else 0

    work_hours, ot_min, half_day = None, 0, False

    if punch_out:
        if punch_out.tzinfo is None:
            punch_out = punch_out.replace(tzinfo=timezone.utc)
            
        # R4 Work Hours
        work_hours = round_half_up((punch_out - punch_in).total_seconds() / 3600, 2)
        # R5 Half Day
        half_day = work_hours < 4.50
        # R3 Overtime
        p_out_ist = punch_out.astimezone(IST)
        h_e, m_e = map(int, shift_end.split(":"))
        end_time = datetime.fromisoformat(att_date).replace(hour=h_e, minute=m_e, tzinfo=IST)
        if h_e <= h_s: end_time += timedelta(days=1)
        
        ot_sec = (p_out_ist - end_time).total_seconds()
        ot_min = int(ot_sec // 60) if ot_sec >= 1800 else 0

    return late_min, work_hours, ot_min, half_day

# --- Pydantic Models for Validation ---

class EmployeeIn(BaseModel):
    emp_code: str = Field(..., pattern=r'^EMP\d{4,6}$')
    name: str
    email: EmailStr
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

# --- Endpoints ---

@app.get("/health")
def health():
    db.command("ping")
    return {"status": "ok"}

@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    db.employees.insert_one(doc)
    doc.pop("_id")
    doc["created_at"] = to_ms(doc["created_at"])
    return doc

@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    q = {"department": department} if department else {}
    items = list(db.employees.find(q, {"_id":0}).sort("emp_code", 1).skip((page-1)*page_size).limit(page_size))
    for i in items: i["created_at"] = to_ms(i["created_at"])
    return {"items": items, "total": db.employees.count_documents(q), "page": page, "page_size": page_size}

@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp: raise HTTPException(404, "Employee not found")
    
    ts = from_ms(body.punched_at) if body.punched_at else datetime.now(timezone.utc)
    
    # Simple attendance date logic
    ist_dt = ts.astimezone(IST)
    date_str = ist_dt.date().isoformat()
    
    late, _, _, _ = calculate_metrics(ts, None, emp["shift_start"], emp["shift_end"], date_str)
    
    doc = {
        "emp_code": body.emp_code, "date": date_str, "status": body.status,
        "punch_in": ts, "punch_out": None, "work_hours": None, "late_minutes": late,
        "overtime_minutes": 0, "half_day": False, "history": []
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Already punched in for this date")
    doc.pop("_id")
    doc["punch_in"] = to_ms(doc["punch_in"])
    return doc

@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    ts_out = from_ms(body.punched_at) if body.punched_at else datetime.now(timezone.utc)
    
    # Find the log that hasn't been punched out yet
    log = db.attendance_logs.find_one({"emp_code": body.emp_code, "punch_out": None}, sort=[("punch_in", -1)])
    if not log: 
        raise HTTPException(404, "No active punch-in found for this employee")
    
    emp = db.employees.find_one({"emp_code": body.emp_code})
    late, work, ot, half = calculate_metrics(log["punch_in"], ts_out, emp["shift_start"], emp["shift_end"], log["date"])
    
    res = db.attendance_logs.find_one_and_update(
        {"_id": log["_id"], "punch_out": None},
        {"$set": {"punch_out": ts_out, "work_hours": work, "overtime_minutes": ot, "half_day": half}},
        return_document=True
    )
    if not res: raise HTTPException(409, "Already punched out")
    res.pop("_id")
    res["punch_in"] = to_ms(res["punch_in"])
    res["punch_out"] = to_ms(res["punch_out"])
    return res

@app.get("/analytics/departments/summary")
def department_summary(month: str = Query(..., pattern=r'^\d{4}-(0[1-9]|1[0-2])$')):
    pipeline = [
        {"$lookup": {
            "from": "attendance_logs",
            "localField": "emp_code",
            "foreignField": "emp_code",
            "as": "logs"
        }},
        {"$unwind": {"path": "$logs", "preserveNullAndEmptyArrays": True}},
        {"$match": {"$or": [{"logs.date": {"$regex": f"^{month}"}}, {"logs": {"$exists": False}}]}},
        {"$group": {
            "_id": "$department",
            "headcount": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": {"$cond": [{"$in": ["$logs.status", ["PRESENT", "WFH", "ON_DUTY"]]}, {"$cond": ["$logs.half_day", 0.5, 1]}, 0]}},
            "avg_work_hours": {"$avg": "$logs.work_hours"},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$logs.late_minutes", 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": "$logs.late_minutes"},
            "leave_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "LEAVE"]}, 1, 0]}},
            "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$logs.status", "ON_DUTY"]}, 1, 0]}}
        }},
        {"$project": {
            "department": "$_id", "_id": 0, "headcount": {"$size": "$headcount"}, "present_days": 1,
            "avg_work_hours": {"$round": ["$avg_work_hours", 2]}, "late_count": 1, 
            "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1
        }},
        {"$sort": {"department": 1}}
    ]
    return {"month": month, "items": list(db.employees.aggregate(pipeline))}