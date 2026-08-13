from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from auth_utils import is_owner, owner_required_response, resolve_accessible_shop
from models import Product, ShopInventory, StockMovement, TransactionItem, db
from utils import parse_excel_products, save_products_to_db
from stock_routes import apply_stock_movement, get_or_create_inventory
import os

api = Blueprint('api', __name__, url_prefix='/api')

ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def product_with_shop_stock(product, shop_id=None):
    data = product.to_dict()
    if not shop_id:
        return data

    inventory = ShopInventory.query.filter_by(
        shop_id=shop_id,
        product_id=product.id,
    ).first()
    data['shopId'] = shop_id
    data['stockLevel'] = inventory.stock_level if inventory else 0
    data['reorderLevel'] = inventory.reorder_level if inventory else product.reorderLevel
    data['inventoryId'] = inventory.id if inventory else None
    return data

@api.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'message': 'API is running'}), 200

@api.route('/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with optional filtering"""
    try:
        # Query parameters
        category = request.args.get('category')
        search = request.args.get('search')
        shop = None
        if request.args.get('shopId') or not is_owner():
            shop = resolve_accessible_shop(request.args.get('shopId'))
        shop_id = shop.id if shop else None
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        include_inactive = request.args.get('includeInactive') == 'true' and is_owner()
        
        query = Product.query
        if not include_inactive:
            query = query.filter(Product.is_active == True)
        
        # Filter by category
        if category and category.lower() != 'all':
            query = query.filter_by(category=category)
        
        # Search by name or code
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (Product.name.ilike(search_term)) | 
                (Product.code.ilike(search_term))
            )
        
        # Pagination
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        products = [product_with_shop_stock(product, shop_id) for product in paginated.items]
        
        return jsonify({
            'success': True,
            'data': products,
            'total': paginated.total,
            'pages': paginated.pages,
            'current_page': page,
            'per_page': per_page
        }), 200

    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@api.route('/products/<product_id>', methods=['GET'])
@jwt_required()
def get_product(product_id):
    """Get a single product by ID"""
    try:
        product = Product.query.get(product_id)
        
        if not product or (not product.is_active and not is_owner()):
            return jsonify({'success': False, 'message': 'Product not found'}), 404
        
        shop = None
        if request.args.get('shopId') or not is_owner():
            shop = resolve_accessible_shop(request.args.get('shopId'))
        shop_id = shop.id if shop else None
        return jsonify({
            'success': True,
            'data': product_with_shop_stock(product, shop_id)
        }), 200

    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@api.route('/products/code/<code>', methods=['GET'])
@jwt_required()
def get_product_by_code(code):
    """Get a product by code (for barcode scanning)"""
    try:
        shop = None
        if request.args.get('shopId') or not is_owner():
            shop = resolve_accessible_shop(request.args.get('shopId'))
        shop_id = shop.id if shop else None
        query = Product.query.filter_by(code=code)
        if not is_owner():
            query = query.filter(Product.is_active == True)
        product = query.first()
        
        if not product:
            return jsonify({'success': False, 'message': 'Product not found'}), 404
        
        return jsonify({
            'success': True,
            'data': product_with_shop_stock(product, shop_id)
        }), 200

    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@api.route('/products/upload', methods=['POST'])
@jwt_required()
def upload_products():
    """Upload and parse Excel file with products"""
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    try:
        # Check if file is in request
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No file provided'
            }), 400
        
        file = request.files['file']
        shop_id = request.form.get('shopId') or request.args.get('shopId')
        try:
            shop = resolve_accessible_shop(shop_id)
        except ValueError as e:
            return jsonify({'success': False, 'message': str(e)}), 400
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'message': 'No file selected'
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'message': 'Only Excel files (.xlsx, .xls) are allowed'
            }), 400
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        from flask import current_app
        upload_dir = current_app.config['UPLOAD_FOLDER']
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        # Parse Excel file
        products, parse_errors = parse_excel_products(file_path)
        
        if not products:
            return jsonify({
                'success': False,
                'message': 'No valid products found',
                'errors': parse_errors
            }), 400
        
        # Save to database
        success_count, duplicate_count, save_errors = save_products_to_db(
            products,
            shop_id=shop.id,
            user_id=get_jwt_identity(),
        )
        
        # Clean up uploaded file
        try:
            os.remove(file_path)
        except:
            pass
        
        all_errors = parse_errors + save_errors
        
        return jsonify({
            'success': True,
            'message': 'Upload successful',
            'summary': {
                'shopId': shop.id,
                'shopName': shop.name,
                'total_processed': len(products),
                'successful': success_count,
                'duplicates_updated': duplicate_count,
                'errors_count': len(all_errors)
            },
            'errors': all_errors
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Upload failed: {str(e)}'
        }), 500

@api.route('/products/<product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    """Update a product"""
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    try:
        product = Product.query.get(product_id)
        
        if not product:
            return jsonify({'success': False, 'message': 'Product not found'}), 404
        
        data = request.get_json()
        
        # Update fields if provided
        if 'name' in data:
            product.name = data['name']
        if 'description' in data:
            product.description = data['description']
        if 'category' in data:
            product.category = data['category']
        if 'costPrice' in data:
            product.costPrice = float(data['costPrice'])
        if 'sellingPrice' in data:
            product.sellingPrice = float(data['sellingPrice'])
        if 'isActive' in data:
            product.is_active = bool(data['isActive'])
        if 'reorderLevel' in data:
            product.reorderLevel = int(data['reorderLevel'])

        if 'stockLevel' in data:
            shop_id = data.get('shopId') or request.args.get('shopId')
            try:
                shop = resolve_accessible_shop(shop_id)
            except ValueError as e:
                return jsonify({'success': False, 'message': str(e)}), 400

            inventory = get_or_create_inventory(shop.id, product.id, product.reorderLevel)
            inventory.reorder_level = int(data.get('reorderLevel', inventory.reorder_level))
            quantity = int(data['stockLevel']) - inventory.stock_level
            apply_stock_movement(
                shop_id=shop.id,
                product_id=product.id,
                movement_type='manual_adjustment',
                quantity=quantity,
                user_id=get_jwt_identity(),
                reason=data.get('stockReason', 'Product stock update'),
                reference_type='product_update',
                reference_id=product.id,
                reorder_level=inventory.reorder_level,
                allow_zero=True,
            )
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Product updated',
            'data': product.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@api.route('/products/<product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    """Delete a product"""
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    try:
        product = Product.query.get(product_id)
        
        if not product:
            return jsonify({'success': False, 'message': 'Product not found'}), 404

        has_inventory = ShopInventory.query.filter_by(product_id=product_id).first()
        has_movements = StockMovement.query.filter_by(product_id=product_id).first()
        has_sales = TransactionItem.query.filter_by(product_id=product_id).first()
        if has_inventory or has_movements or has_sales:
            return jsonify({
                'success': False,
                'message': 'Product has stock or sales history and cannot be deleted; archive it instead'
            }), 409
        
        db.session.delete(product)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Product deleted'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@api.route('/categories', methods=['GET'])
@jwt_required()
def get_categories():
    """Get all unique product categories"""
    try:
        categories = db.session.query(Product.category).distinct().all()
        category_list = [cat[0] for cat in categories if cat[0]]
        
        return jsonify({
            'success': True,
            'data': sorted(category_list)
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@api.route('/stats', methods=['GET'])
@jwt_required()
def get_stats():
    """Get product statistics"""
    owner_error = owner_required_response()
    if owner_error:
        return owner_error

    try:
        shop_id = request.args.get('shopId')
        if shop_id:
            total_products = ShopInventory.query.filter_by(shop_id=shop_id).count()
            total_stock = db.session.query(db.func.sum(ShopInventory.stock_level)).filter(
                ShopInventory.shop_id == shop_id
            ).scalar() or 0
            total_value = db.session.query(
                db.func.sum(ShopInventory.stock_level * Product.sellingPrice)
            ).join(Product, ShopInventory.product_id == Product.id).filter(
                ShopInventory.shop_id == shop_id
            ).scalar() or 0
            low_stock = ShopInventory.query.filter(
                ShopInventory.shop_id == shop_id,
                ShopInventory.stock_level <= ShopInventory.reorder_level,
            ).count()
        else:
            total_products = Product.query.count()
            total_stock = db.session.query(db.func.sum(Product.stockLevel)).scalar() or 0
            total_value = db.session.query(
                db.func.sum(Product.stockLevel * Product.sellingPrice)
            ).scalar() or 0
            low_stock = Product.query.filter(
                Product.stockLevel <= Product.reorderLevel
            ).count()
        
        return jsonify({
            'success': True,
            'data': {
                'total_products': total_products,
                'total_stock_units': int(total_stock),
                'total_inventory_value': float(total_value),
                'low_stock_items': low_stock
            }
        }), 200
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
