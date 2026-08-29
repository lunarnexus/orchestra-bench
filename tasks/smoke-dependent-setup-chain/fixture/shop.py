PRODUCTS = {}
CUSTOMERS = {}
ORDERS = []

def add_product(sku, name, price):
    PRODUCTS[sku] = {'sku': sku, 'name': name, 'price': float(price)}
    return PRODUCTS[sku]

def add_customer(customer_id, name):
    CUSTOMERS[customer_id] = {'customer_id': customer_id, 'name': name, 'cart': []}
    return CUSTOMERS[customer_id]

def add_to_cart(customer_id, sku, quantity):
    customer = CUSTOMERS[customer_id]
    customer['cart'].append({'sku': sku, 'quantity': int(quantity)})

def checkout(customer_id):
    raise NotImplementedError('checkout workflow not implemented')
