"""
Celery task tests — just import-callable smoke tests.
Full execution paths are tested via the integration smoke test (P4T6).
"""
def test_recrawl_stale_pages_task_exists():
    from collector.tasks.celery_app import recrawl_stale_pages
    assert callable(recrawl_stale_pages)


def test_check_dead_links_task_exists():
    from collector.tasks.celery_app import check_dead_links
    assert callable(check_dead_links)


def test_import_cdx_batch_task_exists():
    from collector.tasks.celery_app import import_cdx_batch
    assert callable(import_cdx_batch)
