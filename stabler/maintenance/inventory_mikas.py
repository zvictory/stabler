import frappe

def run():
    company = 'Mikas'
    doctypes = [
        'Tender Master', 'Tender Lot', 'Tender Sourcing Decision', 'CRM Deal', 'CRM Activity', 'CRM Stage Event',
        'Supplier Quotation', 'Quotation', 'Sales Order', 'Purchase Order',
        'Sales Invoice', 'Purchase Invoice', 'Delivery Note', 'Purchase Receipt',
        'Payment Entry', 'Journal Entry', 'Stock Entry', 'Stock Reconciliation',
        'GL Entry', 'Stock Ledger Entry', 'Payment Ledger Entry'
    ]

    print('=== TRANSACTIONAL DOCTYPES INVENTORY ===')
    print('DocType | Mikas Record Count | Draft | Submitted | Cancelled | Foreign Co | Has Company Field | Date Range')
    print('-----------------------------------------------------------------------------------------------------------')
    for dt in doctypes:
        if not frappe.db.exists('DocType', dt):
            print(f'{dt} | NOT_FOUND')
            continue
        
        meta = frappe.get_meta(dt)
        has_company = meta.has_field('company')
        has_docstatus = meta.is_submittable
        
        if has_company:
            total = frappe.db.count(dt, filters={'company': company})
            foreign = frappe.db.count(dt, filters={'company': ['