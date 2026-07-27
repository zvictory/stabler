__version__ = "0.1.0"

# Monkey-patch Babel's Locale.parse to support the custom 'uzc' language code.
# This prevents UnknownLocaleError from crashing date/time formatting in the framework.
try:
	import babel.core
	_orig_locale_parse = babel.core.Locale.parse

	def patched_locale_parse(identifier, sep='_'):
		if isinstance(identifier, str):
			cleaned = identifier.lower().replace('-', '_')
			if cleaned == 'uzc' or cleaned.startswith('uzc_'):
				identifier = 'uz' + identifier[3:]
		return _orig_locale_parse(identifier, sep=sep)

	babel.core.Locale.parse = patched_locale_parse
except Exception:
	pass


# Monkey-patch frappe.get_doc and frappe.get_cached_doc to redirect Language 'uzc'
# requests to 'uz' (Ўзбек). Since 'uzc' does not exist in standard Frappe Language
# doctype table, calling get_doc("Language", "uzc") throws DoesNotExistError 500.
try:
	import frappe
	_orig_get_doc = frappe.get_doc
	_orig_get_cached_doc = frappe.get_cached_doc

	def patched_get_doc(*args, **kwargs):
		if len(args) >= 2 and args[0] == "Language" and args[1] == "uzc":
			args = ("Language", "uz", *args[2:])
		elif kwargs.get("doctype") == "Language" and kwargs.get("name") == "uzc":
			kwargs["name"] = "uz"
		return _orig_get_doc(*args, **kwargs)

	def patched_get_cached_doc(*args, **kwargs):
		if len(args) >= 2 and args[0] == "Language" and args[1] == "uzc":
			args = ("Language", "uz", *args[2:])
		elif kwargs.get("doctype") == "Language" and kwargs.get("name") == "uzc":
			kwargs["name"] = "uz"
		return _orig_get_cached_doc(*args, **kwargs)

	frappe.get_doc = patched_get_doc
	frappe.get_cached_doc = patched_get_cached_doc
except Exception:
	pass
