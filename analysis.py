import ohlc
import techniques
import time
import os
import sys


def fetch_ohlc():
    try:
        ohlc.main_once()
        print("ohlc completed.")
    except Exception as e:
        print(f"Error in ohlc: {e}")

def technical_analysis():
    try:
        techniques.main_once()
        print("technical analysis completed.")
    except Exception as e:
        print(f"Error in techniques: {e}")

def main():
    """Main execution function for OHLC and technical analysis with loop support."""
    
    # Parse command line arguments
    run_as_loop = False
    loop_interval = 300  # Default 5 minutes between loops
    max_loops = None  # None means infinite
    
    # Check for command line arguments
    for arg in sys.argv[1:]:
        if arg.startswith('--loop='):
            loop_value = arg.split('=')[1].lower()
            run_as_loop = loop_value in ['true', 'yes', '1', 'on']
        elif arg.startswith('--interval='):
            try:
                loop_interval = int(arg.split('=')[1])
            except ValueError:
                print(f"Invalid interval value: {arg.split('=')[1]}. Using default 300 seconds.", "WARNING")
        elif arg.startswith('--max-loops='):
            try:
                max_loops = int(arg.split('=')[1])
            except ValueError:
                print(f"Invalid max-loops value: {arg.split('=')[1]}. Running infinite loops.", "WARNING")
    
    print("\n" + "┌" + "─"*58 + "┐", "INFO")
    print("│              🔄 SYNAREX OHLC & TECHNICAL PIPELINE            │", "INFO")
    print("│" + " " * 58 + "│", "INFO")
    print(f"│  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}" + " " * (58 - len(f"│  Loop Mode: {'ENABLED' if run_as_loop else 'DISABLED'}")) + "│", "INFO")
    if run_as_loop:
        print(f"│  Interval: {loop_interval}s" + " " * (58 - len(f"│  Interval: {loop_interval}s")) + "│", "INFO")
        if max_loops:
            print(f"│  Max Loops: {max_loops}" + " " * (58 - len(f"│  Max Loops: {max_loops}")) + "│", "INFO")
        else:
            print("│  Max Loops: Infinite" + " " * (58 - len("│  Max Loops: Infinite")) + "│", "INFO")
    print("└" + "─"*58 + "┘\n", "INFO")
    
    loop_count = 0
    
    while True:
        loop_count += 1
        
        if run_as_loop:
            print("\n" + "="*60, "INFO")
            print(f"🔄 LOOP #{loop_count} STARTED", "INFO")
            print("="*60, "INFO")
        
        # Execute the main pipeline
        try:
            # Fetch OHLC data
            fetch_ohlc()
            
            # Perform technical analysis
            technical_analysis()
            
            print("\n" + "┌" + "─"*58 + "┐", "SUCCESS")
            print("│              ✅ OHLC & TECHNICAL COMPLETED                │", "SUCCESS")
            print("├" + "─"*58 + "┤", "SUCCESS")
            print("│ • OHLC data fetched                • Technical analysis done │", "SUCCESS")
            print("└" + "─"*58 + "┘\n", "SUCCESS")
            
        except Exception as e:
            print("\n" + "┌" + "─"*58 + "┐", "ERROR")
            print("│              OHLC & TECHNICAL PIPELINE FAILED           │", "ERROR")
            print("├" + "─"*58 + "┤", "ERROR")
            print(f"│ Error: {str(e)[:50]}...                                │", "ERROR")
            print("└" + "─"*58 + "┘\n", "ERROR")
        
        # Check loop conditions
        if not run_as_loop:
            # Single execution - exit
            print("🏁 Single execution completed. Exiting...", "INFO")
            break
        
        # Check max loops
        if max_loops and loop_count >= max_loops:
            print(f"🏁 Maximum loops ({max_loops}) reached. Exiting...", "INFO")
            break
        
        # Wait before next iteration
        print(f"⏳ Waiting {loop_interval} seconds before next loop...", "INFO")
        time.sleep(loop_interval)
        
        # Optional: Reload configuration for next loop
        print("🔄 Preparing for next iteration...", "INFO")

    
if __name__ == "__main__":
   main()
