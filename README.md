# 🍔 Uber Eats Lite — Event-Driven Microservices System

A **production-grade Uber Eats clone** built with **FastAPI**, **React**, **AWS SQS/EventBridge**, and **Docker**.  
This project demonstrates **event-driven microservices architecture**, **infrastructure orchestration**, and **cloud-native design** — built for scalability, observability, and developer experience.

---

## 🧭 Overview

**Uber Eats Lite** simulates a real-world food delivery workflow:

1. A user places an order  
2. The order-service creates an event (`order.created`)  
3. The notification-service and driver-service consume the event  
4. A driver is automatically assigned  
5. The payment-service processes payment  
6. Notifications are emitted to the user  

All services communicate asynchronously through **AWS SQS + EventBridge** (locally simulated using **LocalStack**).

---

## 🏗️ Architecture

```text
               ┌────────────────────────────┐
               │        React Frontend      │
               │  (Vite + Tailwind CSS)     │
               └─────────────┬──────────────┘
                             │
                             ▼
                ┌─────────────────────────┐
                │      API Gateway        │
                │  (FastAPI Reverse Proxy)│
                └─────────────────────────┘
        ┌────────────┬────────────┬──────────────┐
        ▼            ▼            ▼              ▼
┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐ ┌────────────┐
│ user-svc   │ │ order-svc  │ │ driver-svc │ │ payment-svc  │ │ notif-svc  │
│ FastAPI    │ │ FastAPI    │ │ FastAPI    │ │ FastAPI      │ │ FastAPI    │
└────────────┘ └────────────┘ └────────────┘ └──────────────┘ └────────────┘
        └──────────────┬──────────────┬──────────────┘
                       │
                       ▼
             ┌────────────────────────┐
             │     AWS SQS +          │
             │   EventBridge (Local)  │
             └────────────────────────┘


---

## ⚙️ Tech Stack
**Frontend:** React (Vite, Tailwind CSS)  
**Backend:** FastAPI microservices (Users, Orders, Drivers, Payments, Notifications)  
**Messaging:** AWS SQS + EventBridge (via LocalStack)  
**Infra:** Docker, Docker Compose  
**Database:** SQLite / PostgreSQL  
**Cloud (previously):** AWS ECS, ECR, ALB, Target Groups, Security Groups

> 🧭 *Originally deployed on AWS ECS with ECR, ALB, Target Groups, and Security Groups.  
Later migrated to Docker Compose + LocalStack for cost optimization while retaining full event-driven flow.*

---

## 🚀 Run Locally

```bash
git clone https://github.com/piyush99755/uber-eats-lite.git
cd uber-eats-lite
docker-compose up --build

