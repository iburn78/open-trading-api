from core.common.optlog import log_filter, grep_logs

if __name__ == "__main__":
    file_name = 'server'
    level='WARNING' # level map key

    start_time=None # '1109_123525.055': same format or None
    end_time=None # 

    log_filter(
        start_time=start_time,
        end_time=end_time,
        level=level,
        infile_name=file_name,
        outfile=None, # auto assign
    )

    search_str = " A1"
    file_name = 'client_runner'

    grep_logs(
        search_str=search_str, 
        infile_name=file_name,
        outfile=None, # auto assign
    )