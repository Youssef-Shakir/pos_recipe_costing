# -*- coding: utf-8 -*-
{
    'name': 'Recipe & Food Costing',
    'version': '18.0.4.0.0',
    'category': 'Point of Sale',
    'summary': 'Restaurant recipe management with BOM/kit integration, stocktaking, and COGS tracking',
    'description': """
Recipe & Food Costing for Restaurants
=====================================
- Dashboard with quick action buttons
- Create and manage recipes with ingredients
- Automatic BOM (Kit) creation for stock consumption
- Track food costs and profit margins
- Quick add forms for ingredients and menu items
- POS products list with easy recipe creation
- Ingredient stocktaking with accounting integration
- Integration with POS for seamless ordering
    """,
    'author': 'Donialink, Yousif Shakir',
    'website': 'https://www.donialink.com',
    'depends': ['point_of_sale', 'mrp', 'stock_account', 'uom', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/ingredient_stocktake_views.xml',
        'wizard/quick_ingredient_views.xml',
        'wizard/quick_product_views.xml',
        'views/dashboard_views.xml',
        'views/restaurant_recipe_views.xml',
        'views/product_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {},
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
    'auto_install': False,
}
