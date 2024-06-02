from analyst import summarize_keyword_conditions, run_dir

c = summarize_keyword_conditions("iphone stand")
c.log_conversation(f"{run_dir}/summary.txt")
