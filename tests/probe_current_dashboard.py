"""Opt-in, isolated transport probe against a supplied Dashboard source tree.

Usage: python3 tests/probe_current_dashboard.py /path/to/dashboard/source
No live Dashboard, Core, wallet or SSH configuration is used or changed.
"""
import sys,unittest
from pathlib import Path

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Supply one Dashboard source directory.')
    dashboard=Path(sys.argv.pop()).resolve()
    if not (dashboard/'nodes.py').is_file():raise SystemExit('Dashboard nodes.py was not found.')
    fixture=Path(__file__).with_name('test_dashboard_integration.py')
    source=fixture.read_text().replace("str(Path(__file__).parent/'fixtures/dashboard_v155')",repr(str(dashboard)))
    source=source.replace('queued=registry.rpc.queue','registry.snapshot();queued=registry.rpc.queue')
    namespace={'__name__':'current_dashboard_probe','__file__':str(fixture)}
    exec(compile(source,str(fixture),'exec'),namespace)
    namespace['setUpModule']()
    try:
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(namespace['DashboardIntegration']))
        if not result.wasSuccessful():raise SystemExit(1)
    finally:namespace['tearDownModule']()
