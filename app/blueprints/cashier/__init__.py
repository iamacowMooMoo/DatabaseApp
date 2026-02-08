from flask import Blueprint

cashier_bp = Blueprint('cashier', __name__)

# Import all sub-modules to register their routes
from . import routes
from . import transactions
from . import services
from . import payments
from . import customers
from . import routes_redis
from . import cache_utils