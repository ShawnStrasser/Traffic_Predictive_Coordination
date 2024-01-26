from flask import Flask, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import duckdb
from get_volume_occupancy import GetVolumeOccupancy
import plotly.io as pio
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import plotly.express as px


# Instatiate classes
app = Flask(__name__)
scheduler = BackgroundScheduler()
get_volume_occupancy = GetVolumeOccupancy()

# Open connection to database
con = duckdb.connect(database="database.db", read_only=False)
print("Opened database successfully")

# Load default settings from database
interval = con.execute("SELECT value FROM Settings WHERE setting = 'interval'").fetchone()[0]
mode = con.execute("SELECT value FROM Settings WHERE setting = 'mode'").fetchone()[0]
run_app = con.execute("SELECT value FROM Settings WHERE setting = 'run_app'").fetchone()[0]
diagnostic_mode = con.execute("SELECT value FROM Settings WHERE setting = 'debug'").fetchone()[0]
signals = con.execute("SELECT * FROM Signals").fetchall() # list of tuples like [('Signal', 'IP'), ('Signal', 'IP')]
# Convert to boolean
run_app = run_app == 'True'
diagnostic_mode = diagnostic_mode == 'True'

print(signals)

# Define the job
def get_data_job():
    print(f"Hello World at {interval}-minute interval. Mode:", mode, " - Diagnostic Mode:", diagnostic_mode)
    get_volume_occupancy.get_data(con, signals)
    con.execute("CHECKPOINT") # Force a checkpoint to move data from wal to database file



# Start the scheduler if run_app is True
job = None
if run_app:
    job = scheduler.add_job(get_data_job, trigger=CronTrigger(minute=f'*/{interval}', second=5))
    scheduler.start()

@app.route('/')
def home():
    job_status = 'ON' if job else 'OFF'
    change_job_status = 'OFF' if job else 'ON'
    diagnostic_status = 'ON' if diagnostic_mode else 'OFF'
    return render_template('configure.html', job_status=job_status, change_job_status=change_job_status, mode=mode, diagnostic_status=diagnostic_status, refresh_interval=interval)

# Toggle the scheduler
@app.route('/toggle')
def toggle():
    global job
    global con
    if job:
        scheduler.remove_job(job.id)
        job = None
        con.execute("UPDATE Settings SET value = 'False' WHERE setting = 'run_app'")
        con.close()
    else:
        job = scheduler.add_job(get_data_job, trigger=CronTrigger(minute=f'*/{interval}', second=5))
        if not scheduler.running:
            scheduler.start()
        con = duckdb.connect(database="database.db", read_only=False)
        con.execute("UPDATE Settings SET value = 'True' WHERE setting = 'run_app'")
    return home()

# Toggle mode between traffic responsive and traffic predictive
@app.route('/toggle_mode')
def toggle_mode():
    global mode
    mode = "Traffic Predictive" if mode == "Traffic Responsive" else "Traffic Responsive"
    con = duckdb.connect(database="database.db", read_only=False)
    con.execute("UPDATE Settings SET value = '" + mode + "' WHERE setting = 'mode'")
    con.close()
    return home()

# Toggle diagnostic mode
@app.route('/toggle_diagnostic')
def toggle_diagnostic():
    global diagnostic_mode
    diagnostic_mode = not diagnostic_mode
    con = duckdb.connect(database="database.db", read_only=False)
    con.execute("UPDATE Settings SET value = '" + str(diagnostic_mode) + "' WHERE setting = 'debug'")
    con.close()
    return home()


# Reports page
@app.route('/reports')
def reports():
    # Get data
    volume_sql = "SELECT signal || ' - Det ' || detector::VARCHAR AS detector, timestamp, volume FROM Volumes ORDER BY timestamp"
    occupancy_sql = "SELECT signal || ' - Det ' || detector::VARCHAR AS detector, timestamp, occupancy FROM Occupancies ORDER BY timestamp"
    try:
        volume = con.execute(volume_sql).fetchdf()
        occupancy = con.execute(occupancy_sql).fetchdf()
    except:
        with duckdb.connect(database="database.db", read_only=True) as temp_con:
            volume = temp_con.execute(volume_sql).fetchdf()
            occupancy = temp_con.execute(occupancy_sql).fetchdf()

    # Create subplots
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.2,
                        subplot_titles=('Volume', 'Occupancy'))

    # Create a color map for detectors
    unique_detectors = pd.concat([volume['detector'], occupancy['detector']]).unique()
    #print(unique_detectors)
    colors = px.colors.qualitative.Plotly  # or any other color sequence
    color_map = {det: colors[i % len(colors)] for i, det in enumerate(unique_detectors)}

    # Plot volume data with consistent colors
    for key, grp in volume.groupby('detector'):
        fig.add_trace(go.Scatter(x=grp['timestamp'], y=grp['volume'], mode='lines', name=key,
                                 line=dict(color=color_map[key])), row=1, col=1)

    # Plot occupancy data with consistent colors
    for key, grp in occupancy.groupby('detector'):
        fig.add_trace(go.Scatter(x=grp['timestamp'], y=grp['occupancy'], mode='lines', name=key,
                                 line=dict(color=color_map[key]), showlegend=False), row=2, col=1)

    # Update layout
    fig.update_layout(height=600, title_text="Volume and Occupancy by Detector")
    #fig.update_xaxes(title_text='Timestamp', row=2, col=1)
    # Manually show x-axis on both subplots
    fig.update_xaxes(row=1, col=1, showticklabels=True)
    fig.update_xaxes(row=2, col=1, showticklabels=True)

    fig.update_yaxes(title_text=f"Vehicles/{interval}-minute", row=1, col=1)
    fig.update_yaxes(title_text="Occupancy", row=2, col=1, tickformat=".0%", range=[0, 1])

    # Convert the figure to HTML
    plot_html = pio.to_html(fig, full_html=False)

    return render_template('reports.html', plot_html=plot_html, refresh_interval=interval)

# Logs page
@app.route('/logs', methods=['GET', 'POST'])
def logs():
    filter_event = request.args.get('event')  # Get the filter event from the request

    # Get data
    sql_data = "SELECT * FROM Logs"
    sql_types = "SELECT DISTINCT event FROM Logs"
    if filter_event:
        sql_data += f" WHERE event = '{filter_event}'"
    sql_data += " ORDER BY timestamp DESC"
    try:
        logs = con.execute(sql_data).fetchdf()
        # Get unique event types for the dropdown
        event_types = con.execute(sql_types).fetchdf()['event'].tolist()
    except:
        with duckdb.connect(database="database.db", read_only=True) as temp_con:
            logs = temp_con.execute(sql_data).fetchdf()
            event_types = con.execute(sql_types).fetchdf()['event'].tolist()

    # Convert the dataframe to HTML
    logs_html = logs.to_html(index=False, classes='logs-table')

    return render_template('logs.html', logs_html=logs_html, refresh_interval=interval, event_types=event_types, current_filter=filter_event)


if __name__ == '__main__':
    app.run(debug=False, use_reloader=False)
