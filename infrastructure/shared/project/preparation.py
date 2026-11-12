"""Bounded, reported preparation recovery before native implementation tasks."""

from infrastructure.utils.files import save_json


def prepare_with_recovery(arc_dir, steps, console, *, report_name):
    report = {'status':'PREPARING','steps':{}}
    path = arc_dir/report_name
    for name, action in steps:
        entry = report['steps'][name] = {'status':'RUNNING','attempts':[]}
        for attempt in range(2):
            save_json(path,report)
            try:
                action()
                entry['status'] = 'GREEN'
                entry['attempts'].append({'attempt':attempt+1,'status':'GREEN'})
                break
            except (ValueError,RuntimeError,OSError) as error:
                entry['attempts'].append({'attempt':attempt+1,'status':'FAILED',
                    'error_type':type(error).__name__,'error':str(error)[:2000]})
                if attempt==0 and isinstance(error,(RuntimeError,OSError)):
                    console.show('Environment preparation | '+name+' | Retry',
                        'Preparation failed; retry once before ending this stage. Accepted application files are retained.\n'+str(error)[:1000])
                    continue
                entry['status'] = report['status'] = 'FAILED'
                report['error'] = 'Environment preparation failed at '+name+'; repair the recorded cause and resume this stage.'
                save_json(path,report)
                return report
        save_json(path,report)
    report['status'] = 'GREEN'
    save_json(path,report)
    return report
