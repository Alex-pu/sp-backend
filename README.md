# Flask Products API Backend

Simple Flask backend for uploading and managing products via Excel files.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create Virtual Environment (Optional but Recommended)

```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

### 3. Run the Server

```bash
python app.py
```

The API will be available at `http://localhost:5000`

## API Endpoints

### Product Management

- **GET** `/api/products` - Get all products with pagination
  - Query params: `page`, `per_page`, `category`, `search`

- **GET** `/api/products/<product_id>` - Get a specific product

- **GET** `/api/products/code/<code>` - Get product by code (useful for barcode scanning)

- **POST** `/api/products/upload` - Upload Excel file with products
  - Content-Type: `multipart/form-data`
  - File field: `file`

- **PUT** `/api/products/<product_id>` - Update a product

- **DELETE** `/api/products/<product_id>` - Delete a product

### Utilities

- **GET** `/api/categories` - Get all product categories

- **GET** `/api/stats` - Get inventory statistics

- **GET** `/api/health` - Health check

### Device Pairing

- **POST** `/api/device-invites` - Owner creates a one-time shop pairing token
  - JSON: `shopId`, optional `deviceLabel`, optional `expiresInHours`

- **GET** `/api/device-invites/<token>` - Preview the shop linked to an active token

- **POST** `/api/device-invites/<token>/accept` - Mobile device accepts the invite
  - JSON: `deviceId`, optional `deviceLabel`

## Excel File Format

Upload an Excel file with the following columns (header row required):

| Column | Type | Required | Notes |
|--------|------|----------|-------|
| code | String | Yes | Unique product code/SKU |
| name | String | Yes | Product name |
| category | String | No | Product category (default: "General") |
| description | String | No | Product description |
| costPrice | Float | No | Cost price (default: 0) |
| sellingPrice | Float | Yes | Selling price |
| stockLevel | Integer | No | Current stock (default: 0) |
| reorderLevel | Integer | No | Stock reorder level (default: 10) |

### Example Excel File:
```
code        | name              | category    | costPrice | sellingPrice | stockLevel | reorderLevel
SKU001      | Product A         | Electronics | 5000      | 8000         | 25         | 5
SKU002      | Product B         | Accessories | 1500      | 2500         | 50         | 10
SKU003      | Product C         | General     | 3000      | 5000         | 15         | 3
```

## Usage from Flutter App

### 1. Fetch Products

```dart
final response = await http.get(
  Uri.parse('http://localhost:5000/api/products?page=1&per_page=50'),
);
```

### 2. Search Products

```dart
final response = await http.get(
  Uri.parse('http://localhost:5000/api/products?search=product_name'),
);
```

### 3. Get Product by Code

```dart
final response = await http.get(
  Uri.parse('http://localhost:5000/api/products/code/SKU001'),
);
```

### 4. Upload Products from Excel

```dart
var request = http.MultipartRequest(
  'POST',
  Uri.parse('http://localhost:5000/api/products/upload'),
);
request.files.add(await http.MultipartFile.fromPath('file', excelFilePath));
var response = await request.send();
```

## Database

- **Type**: SQLite
- **File**: `sp_products.db` (auto-created)
- **Location**: Project root directory

## Notes

- Max file size: 16MB
- Allowed formats: `.xlsx`, `.xls`
- Duplicate codes update existing products
- CORS is enabled for cross-origin requests

## Troubleshooting

**Port already in use?**
```bash
# Change port in app.py or run on different port
python app.py --port 5001
```

**Excel parsing errors?**
- Ensure Excel file has headers in first row
- Check column names match expected names (case-insensitive)
- Ensure required columns (code, name, sellingPrice) have values

**Database errors?**
- Delete `sp_products.db` to reset database
- Ensure write permissions in project directory
