from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

db = SQLAlchemy()

class Shop(db.Model):
    """A physical shop/branch in the business."""
    __tablename__ = 'shops'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(120), nullable=False, unique=True)
    location = db.Column(db.String(255), default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    users = db.relationship('User', backref='shop', lazy=True)
    shifts = db.relationship('Shift', backref='shop', lazy=True)
    transactions = db.relationship('Transaction', backref='shop', lazy=True)
    expenses = db.relationship('Expense', backref='shop', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'location': self.location,
            'isActive': self.is_active,
            'createdAt': self.created_at.isoformat(),
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Shop {self.name}>'


class Product(db.Model):
    """Product model for SQLAlchemy"""
    __tablename__ = 'products'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default='')
    category = db.Column(db.String(100), default='General')
    
    # Pricing
    costPrice = db.Column(db.Float, default=0.0)
    sellingPrice = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    
    # Inventory
    stockLevel = db.Column(db.Integer, default=0)
    reorderLevel = db.Column(db.Integer, default=10)
    
    # Metadata
    createdAt = db.Column(db.DateTime, default=datetime.utcnow)
    updatedAt = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        """Convert product to dictionary for JSON response"""
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'costPrice': self.costPrice,
            'sellingPrice': self.sellingPrice,
            'isActive': self.is_active,
            'stockLevel': self.stockLevel,
            'reorderLevel': self.reorderLevel,
            'createdAt': self.createdAt.isoformat(),
            'updatedAt': self.updatedAt.isoformat(),
        }
    
    def __repr__(self):
        return f'<Product {self.name} ({self.code})>'


class ShopInventory(db.Model):
    """Current stock level for one product in one shop."""
    __tablename__ = 'shop_inventory'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shop_id = db.Column(db.String(36), db.ForeignKey('shops.id'), nullable=False)
    product_id = db.Column(db.String(36), db.ForeignKey('products.id'), nullable=False)
    stock_level = db.Column(db.Integer, default=0)
    reorder_level = db.Column(db.Integer, default=10)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    shop = db.relationship('Shop', backref='inventory_items', lazy=True)
    product = db.relationship('Product', backref='shop_inventory', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('shop_id', 'product_id', name='uq_shop_inventory_shop_product'),
    )

    def to_dict(self):
        product = self.product
        return {
            'id': self.id,
            'shopId': self.shop_id,
            'shopName': self.shop.name if self.shop else None,
            'productId': self.product_id,
            'code': product.code if product else None,
            'name': product.name if product else None,
            'description': product.description if product else '',
            'category': product.category if product else None,
            'costPrice': product.costPrice if product else 0.0,
            'sellingPrice': product.sellingPrice if product else 0.0,
            'isActive': product.is_active if product else False,
            'stockLevel': self.stock_level,
            'reorderLevel': self.reorder_level,
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<ShopInventory shop={self.shop_id} product={self.product_id} stock={self.stock_level}>'


class StockMovement(db.Model):
    """Append-only audit trail for stock changes."""
    __tablename__ = 'stock_movements'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shop_id = db.Column(db.String(36), db.ForeignKey('shops.id'), nullable=False, index=True)
    product_id = db.Column(db.String(36), db.ForeignKey('products.id'), nullable=False, index=True)
    type = db.Column(db.String(30), nullable=False)  # sale, stock_received, manual_adjustment, void
    quantity = db.Column(db.Integer, nullable=False)
    stock_before = db.Column(db.Integer, nullable=False)
    stock_after = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text, default='')
    reference_type = db.Column(db.String(50), default='')
    reference_id = db.Column(db.String(100), default='')
    created_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    shop = db.relationship('Shop', backref='stock_movements', lazy=True)
    product = db.relationship('Product', backref='stock_movements', lazy=True)
    user = db.relationship('User', backref='stock_movements', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'shopId': self.shop_id,
            'shopName': self.shop.name if self.shop else None,
            'productId': self.product_id,
            'productCode': self.product.code if self.product else None,
            'productName': self.product.name if self.product else None,
            'type': self.type,
            'quantity': self.quantity,
            'stockBefore': self.stock_before,
            'stockAfter': self.stock_after,
            'reason': self.reason,
            'referenceType': self.reference_type,
            'referenceId': self.reference_id,
            'createdBy': self.created_by,
            'createdByName': self.user.name if self.user else None,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<StockMovement {self.type} {self.quantity}>'


class User(db.Model):
    """Cashier / Owner account"""
    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False, unique=True)
    pin_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='cashier')   # 'owner' or 'cashier'
    shop_id = db.Column(db.String(36), db.ForeignKey('shops.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    createdAt = db.Column(db.DateTime, default=datetime.utcnow)

    shifts = db.relationship('Shift', backref='cashier', lazy=True)

    def set_pin(self, pin):
        self.pin_hash = generate_password_hash(str(pin))

    def check_pin(self, pin):
        return check_password_hash(self.pin_hash, str(pin))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'role': self.role,
            'shopId': self.shop_id,
            'shopName': self.shop.name if self.shop else None,
            'isActive': self.is_active,
            'createdAt': self.createdAt.isoformat(),
        }

    def __repr__(self):
        return f'<User {self.name} ({self.role})>'


class DeviceInvite(db.Model):
    """One-time token used to link a mobile device to a shop."""
    __tablename__ = 'device_invites'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shop_id = db.Column(db.String(36), db.ForeignKey('shops.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_by = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    device_label = db.Column(db.String(120), default='')
    status = db.Column(db.String(20), default='active', index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    accepted_device_id = db.Column(db.String(120), default='')
    accepted_device_label = db.Column(db.String(120), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    shop = db.relationship('Shop', backref='device_invites', lazy=True)
    creator = db.relationship('User', backref='created_device_invites', lazy=True)

    def is_valid(self, now=None):
        now = now or datetime.utcnow()
        return self.status == 'active' and self.expires_at > now and self.shop and self.shop.is_active

    def to_dict(self):
        return {
            'id': self.id,
            'shopId': self.shop_id,
            'shopName': self.shop.name if self.shop else None,
            'deviceLabel': self.device_label,
            'status': self.status,
            'expiresAt': self.expires_at.isoformat(),
            'acceptedAt': self.accepted_at.isoformat() if self.accepted_at else None,
            'acceptedDeviceId': self.accepted_device_id,
            'acceptedDeviceLabel': self.accepted_device_label,
            'createdAt': self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<DeviceInvite shop={self.shop_id} status={self.status}>'


class Shift(db.Model):
    """A cashier's work session — from opening float to cash reconciliation"""
    __tablename__ = 'shifts'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cashier_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    shop_id = db.Column(db.String(36), db.ForeignKey('shops.id'), nullable=True)
    cashier_name = db.Column(db.String(100), nullable=False)
    opening_float = db.Column(db.Float, default=0.0)
    closing_cash = db.Column(db.Float, nullable=True)
    expected_cash = db.Column(db.Float, nullable=True)
    variance = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), default='open')    # 'open' or 'closed'
    notes = db.Column(db.Text, default='')
    opened_at = db.Column(db.DateTime, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)

    transactions = db.relationship('Transaction', backref='shift', lazy=True)
    expenses = db.relationship('Expense', backref='shift', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'cashierId': self.cashier_id,
            'shopId': self.shop_id,
            'shopName': self.shop.name if self.shop else None,
            'cashierName': self.cashier_name,
            'openingFloat': self.opening_float,
            'closingCash': self.closing_cash,
            'expectedCash': self.expected_cash,
            'variance': self.variance,
            'status': self.status,
            'notes': self.notes,
            'openedAt': self.opened_at.isoformat(),
            'closedAt': self.closed_at.isoformat() if self.closed_at else None,
        }

    def __repr__(self):
        return f'<Shift {self.cashier_name} {self.status}>'


class Transaction(db.Model):
    """A completed sale — synced from Flutter, immutable once stored"""
    __tablename__ = 'transactions'

    id = db.Column(db.String(36), primary_key=True)   # UUID from Flutter (idempotent)
    receipt_number = db.Column(db.String(50), unique=True, nullable=False)
    shift_id = db.Column(db.String(36), db.ForeignKey('shifts.id'), nullable=True)
    shop_id = db.Column(db.String(36), db.ForeignKey('shops.id'), nullable=True)
    cashier_id = db.Column(db.String(36), nullable=False)
    cashier_name = db.Column(db.String(100), nullable=False)
    subtotal = db.Column(db.Float, default=0.0)
    discount_total = db.Column(db.Float, default=0.0)
    tax_total = db.Column(db.Float, default=0.0)
    grand_total = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), default='cash')
    is_split_bill = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='completed')   # 'completed' or 'voided'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    synced_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('TransactionItem', backref='transaction', lazy=True,
                            cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='transaction', lazy=True,
                               cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'receiptNumber': self.receipt_number,
            'shiftId': self.shift_id,
            'shopId': self.shop_id,
            'shopName': self.shop.name if self.shop else None,
            'cashierId': self.cashier_id,
            'cashierName': self.cashier_name,
            'subtotal': self.subtotal,
            'discountTotal': self.discount_total,
            'taxTotal': self.tax_total,
            'grandTotal': self.grand_total,
            'paymentMethod': self.payment_method,
            'isSplitBill': self.is_split_bill,
            'status': self.status,
            'items': [item.to_dict() for item in self.items],
            'payments': [p.to_dict() for p in self.payments],
            'createdAt': self.created_at.isoformat(),
            'syncedAt': self.synced_at.isoformat(),
        }

    def __repr__(self):
        return f'<Transaction {self.receipt_number}>'


class TransactionItem(db.Model):
    """A single line item within a transaction — price is snapshotted at time of sale"""
    __tablename__ = 'transaction_items'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = db.Column(db.String(36), db.ForeignKey('transactions.id'), nullable=False)
    product_id = db.Column(db.String(36), nullable=True)
    product_code = db.Column(db.String(50), nullable=False)
    product_name = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)   # snapshotted
    discount = db.Column(db.Float, default=0.0)
    line_total = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'transactionId': self.transaction_id,
            'productId': self.product_id,
            'productCode': self.product_code,
            'productName': self.product_name,
            'quantity': self.quantity,
            'unitPrice': self.unit_price,
            'discount': self.discount,
            'lineTotal': self.line_total,
        }


class Payment(db.Model):
    """One payment leg — multiple per transaction when split bill"""
    __tablename__ = 'payments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = db.Column(db.String(36), db.ForeignKey('transactions.id'), nullable=False)
    method = db.Column(db.String(50), nullable=False)   # cash, mpesa, card
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(100), default='')
    phone_number = db.Column(db.String(20), default='')
    card_last4 = db.Column(db.String(4), default='')

    def to_dict(self):
        return {
            'id': self.id,
            'transactionId': self.transaction_id,
            'method': self.method,
            'amount': self.amount,
            'reference': self.reference,
            'phoneNumber': self.phone_number,
            'cardLast4': self.card_last4,
        }


class Expense(db.Model):
    """Cash paid out from the till during a shift"""
    __tablename__ = 'expenses'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    shift_id = db.Column(db.String(36), db.ForeignKey('shifts.id'), nullable=True)
    shop_id = db.Column(db.String(36), db.ForeignKey('shops.id'), nullable=True)
    cashier_id = db.Column(db.String(36), nullable=False)
    cashier_name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, default='')
    payment_method = db.Column(db.String(50), default='cash')
    approval_status = db.Column(db.String(20), default='pending')  # pending/approved/rejected
    approved_by = db.Column(db.String(100), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'shiftId': self.shift_id,
            'shopId': self.shop_id,
            'shopName': self.shop.name if self.shop else None,
            'cashierId': self.cashier_id,
            'cashierName': self.cashier_name,
            'category': self.category,
            'amount': self.amount,
            'description': self.description,
            'paymentMethod': self.payment_method,
            'approvalStatus': self.approval_status,
            'approvedBy': self.approved_by,
            'createdAt': self.created_at.isoformat(),
        }

    def __repr__(self):
        return f'<Expense {self.category} {self.amount}>'


class EtimsConfig(db.Model):
    """eTIMS / KRA configuration  — single row per installation."""
    __tablename__ = 'etims_config'

    id = db.Column(db.Integer, primary_key=True)
    kra_pin = db.Column(db.String(50), default='')
    business_name = db.Column(db.String(200), default='')
    branch_id = db.Column(db.String(20), default='001')
    device_serial = db.Column(db.String(100), default='POS-001')
    device_id = db.Column(db.String(100), default='')       # returned by KRA
    device_registered = db.Column(db.Boolean, default=False)
    environment = db.Column(db.String(20), default='sandbox')   # sandbox | production
    mode = db.Column(db.String(20), default='disabled')          # disabled | optional | strict
    client_id_encrypted = db.Column(db.Text, default='')         # AES-Fernet encrypted
    client_secret_encrypted = db.Column(db.Text, default='')     # AES-Fernet encrypted
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'kraPin': self.kra_pin,
            'businessName': self.business_name,
            'branchId': self.branch_id,
            'deviceSerial': self.device_serial,
            'deviceId': self.device_id,
            'deviceRegistered': self.device_registered,
            'environment': self.environment,
            'mode': self.mode,
            'hasCredentials': bool(self.client_id_encrypted),
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<EtimsConfig env={self.environment} mode={self.mode}>'


class EtimsInvoiceLog(db.Model):
    """Tracks every eTIMS invoice submission attempt."""
    __tablename__ = 'etims_invoice_log'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = db.Column(db.String(36), nullable=False, index=True)
    receipt_number = db.Column(db.String(50), nullable=False)
    etims_status = db.Column(db.String(20), default='queued')   # queued | submitted | approved | failed
    etims_invoice_number = db.Column(db.String(100), default='')  # KRA-assigned invoice number
    qr_data = db.Column(db.Text, default='')                      # base64-encoded QR image from KRA
    signature = db.Column(db.String(500), default='')
    error_message = db.Column(db.Text, default='')
    retries = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'transactionId': self.transaction_id,
            'receiptNumber': self.receipt_number,
            'etimsStatus': self.etims_status,
            'etimsInvoiceNumber': self.etims_invoice_number,
            'qrData': self.qr_data,
            'signature': self.signature,
            'errorMessage': self.error_message,
            'retries': self.retries,
            'createdAt': self.created_at.isoformat(),
            'updatedAt': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<EtimsInvoiceLog {self.receipt_number} ({self.etims_status})>'
