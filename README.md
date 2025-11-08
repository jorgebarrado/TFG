# TFG Project: Incorrect Citation-Checking Tool

This project is a web application designed to help researchers identify and report incorrect citations in academic papers. Users can submit DOIs of papers, view citing articles, and flag citations that are misinterpreted, out of context, or otherwise incorrect.

## Features

- **User Authentication:** Users can register and log in to report incorrect citations, comment on reports, and save reports for later.
- **DBLP Integration:** Users can link their DBLP profile to easily access and check their own publications.
- **Citation-Checking:** The tool uses the Semantic Scholar and CrossRef APIs to fetch citation data.
- **Community-Driven Reporting:** Users can submit reports on incorrect citations, providing a reason and categorization for the error.
- **Voting and Discussion:** Each report has a comment section for discussion and a voting system to gauge the validity of the report.

## Tech Stack

- **Backend:** Django, Django REST Framework
- **Frontend:** HTML, CSS, JavaScript, Bootstrap
- **Database:** SQLite (for development)
- **APIs:** Semantic Scholar, CrossRef, DBLP

## Setup and Installation

### Prerequisites

- Python 3.8+
- Pip and Virtualenv

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd tfg-project
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

3. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Apply database migrations:**
   ```bash
   python tfg_project/manage.py migrate
   ```

5. **Create a superuser:**
   ```bash
   python tfg_project/manage.py createsuperuser
   ```

6. **Run the development server:**
   ```bash
   python tfg_project/manage.py runserver
   ```

The application will be available at `http://127.0.0.1:8000/`.

## Usage

1. **Register or Log In:** Create an account or log in to access all features.
2. **Link DBLP Profile:** Go to "Account Settings" to add your DBLP profile URL. This will allow you to easily view your publications and their citations.
3. **Submit a Report:** Use the "Submit" page to report an incorrect citation. You will need the DOI of the original paper and the DOI of the paper that contains the incorrect citation.
4. **Browse and Discuss:** View existing reports on the "List" page, and participate in discussions by adding comments and voting.
