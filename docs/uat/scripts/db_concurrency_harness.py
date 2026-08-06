"""Multi-process DB Concurrency Harness for Local Bench Site (stabler).

Executes two independent parallel worker processes synchronized via multiprocessing.Barrier
to hit MariaDB duplicate-key race conditions simultaneously.
Outputs empirical single-row database evidence to docs/uat/evidence/2026-08-02-browser-final/db_concurrency_results.json.
"""

import os
import sys

BENCH_PATH = "/Users/zafar/frappe-bench-local"
SITES_PATH = os.path.join(BENCH_PATH, "sites")

os.chdir(SITES_PATH)
sys.path.insert(0, os.path.join(BENCH_PATH, "apps", "frappe"))
sys.path.insert(0, os.path.join(BENCH_PATH, "apps", "stabler"))

import json
import multiprocessing


def worker_send_email(company, deal, idempotency_key, barrier, result_queue):
	os.chdir(SITES_PATH)
	import frappe

	frappe.init(site="stabler", sites_path=SITES_PATH)
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		from stabler.api import crm_email

		barrier.wait()  # Synchronize workers to fire simultaneously
		res = crm_email.send_deal_email(
			deal=deal,
			subject="Concurrency Race Test",
			content="Race condition email test",
			company=company,
			recipients="test@example.com",
			idempotency_key=idempotency_key,
		)
		frappe.db.commit()
		result_queue.put({"pid": os.getpid(), "res": res, "error": None})
	except Exception as err:
		result_queue.put({"pid": os.getpid(), "res": None, "error": str(err)})
	finally:
		frappe.destroy()


def worker_automation_rule(company, deal, rule_key, barrier, result_queue):
	os.chdir(SITES_PATH)
	import frappe

	frappe.init(site="stabler", sites_path=SITES_PATH)
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		from stabler.api import crm_automation

		barrier.wait()
		res = crm_automation._process_automation_rule_action(
			company=company,
			deal_name=deal,
			rule_name="SLA Deadline Alert",
			rule_key=rule_key,
			action_detail="Parallel race test",
			due_at="2026-08-05",
			dry_run=False,
		)
		frappe.db.commit()
		result_queue.put({"pid": os.getpid(), "executed": res, "error": None})
	except Exception as err:
		result_queue.put({"pid": os.getpid(), "executed": None, "error": str(err)})
	finally:
		frappe.destroy()


def run_concurrency_test():
	os.chdir(SITES_PATH)
	import frappe

	frappe.init(site="stabler", sites_path=SITES_PATH)
	frappe.connect()
	frappe.set_user("Administrator")

	key_comm = "CONCURRENCY-RACE-COMM-001"
	key_act = "CONCURRENCY-RACE-ACT-001"
	comp = "Mikas"
	deal = "CRM-DEAL-2026-00005"

	# Cleanup pre-existing test keys if any
	full_key_comm = f"comm:{comp}:{key_comm}"
	frappe.db.sql("DELETE FROM tabCommunication WHERE custom_idempotency_key = %s", (full_key_comm,))
	frappe.db.sql("DELETE FROM `tabCRM Activity` WHERE custom_idempotency_key = %s", (key_act,))
	frappe.db.commit()
	frappe.destroy()

	# 1. Communication Concurrency Race
	barrier_comm = multiprocessing.Barrier(2)
	q_comm = multiprocessing.Queue()
	p1 = multiprocessing.Process(target=worker_send_email, args=(comp, deal, key_comm, barrier_comm, q_comm))
	p2 = multiprocessing.Process(target=worker_send_email, args=(comp, deal, key_comm, barrier_comm, q_comm))

	p1.start()
	p2.start()
	p1.join()
	p2.join()

	res_comm = []
	while not q_comm.empty():
		res_comm.append(q_comm.get())

	# 2. CRM Activity Concurrency Race
	barrier_act = multiprocessing.Barrier(2)
	q_act = multiprocessing.Queue()
	p3 = multiprocessing.Process(
		target=worker_automation_rule, args=(comp, deal, key_act, barrier_act, q_act)
	)
	p4 = multiprocessing.Process(
		target=worker_automation_rule, args=(comp, deal, key_act, barrier_act, q_act)
	)

	p3.start()
	p4.start()
	p3.join()
	p4.join()

	res_act = []
	while not q_act.empty():
		res_act.append(q_act.get())

	# 3. Query MariaDB to prove single row created per unique key
	frappe.init(site="stabler", sites_path=SITES_PATH)
	frappe.connect()

	comm_rows = frappe.db.sql(
		"SELECT name, custom_idempotency_key, custom_execution_status FROM tabCommunication WHERE custom_idempotency_key = %s",
		(full_key_comm,),
		as_dict=True,
	)
	act_rows = frappe.db.sql(
		"SELECT name, custom_idempotency_key, custom_execution_status FROM `tabCRM Activity` WHERE custom_idempotency_key = %s",
		(key_act,),
		as_dict=True,
	)
	frappe.destroy()

	summary = {
		"communication_race": {
			"workers_result": res_comm,
			"db_rows_found": len(comm_rows),
			"db_records": comm_rows,
			"single_row_verified": len(comm_rows) == 1,
		},
		"crm_activity_race": {
			"workers_result": res_act,
			"db_rows_found": len(act_rows),
			"db_records": act_rows,
			"single_row_verified": len(act_rows) == 1,
		},
	}

	out_dir = "/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-02-browser-final"
	os.makedirs(out_dir, exist_ok=True)
	out_file = os.path.join(out_dir, "db_concurrency_results.json")
	with open(out_file, "w", encoding="utf-8") as f:
		json.dump(summary, f, indent=2, default=str)

	print(f"DB Concurrency harness finished. Results written to {out_file}")


if __name__ == "__main__":
	multiprocessing.set_start_method("fork")
	run_concurrency_test()
