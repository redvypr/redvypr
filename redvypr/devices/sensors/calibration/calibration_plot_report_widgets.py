import datetime
import os.path
from PyQt6 import QtWidgets, QtCore, QtGui
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
import tempfile
import numpy as np
import logging
import sys
import yaml
from redvypr.redvypr_address import RedvyprAddress
import redvypr.files as redvypr_files
from .calibration_models import CalibrationHeatFlow, CalibrationNTC, CalibrationPoly, CalibrationData
_logo_file = redvypr_files.logo_file
_icon_file = redvypr_files.icon_file


logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.device.calibration')
logger.setLevel(logging.DEBUG)


figsize_report_plot = (8,6)

def plot_calibration(calibration, figure):
    # Get the data ready
    try:
        refchannel = calibration.calibration_reference_data.channel.datakey
    except:
        refchannel = calibration.calibration_reference_data.channel

    try:
        channel = calibration.channel.datakey
    except:
        channel = calibration.channel

    refdata = np.asarray(calibration.calibration_reference_data.data)
    caldata = np.asarray(calibration.calibration_data.data)

    # Convert the data
    convdata_calc = calibration.raw2data(caldata)
    convdata_diff = refdata - convdata_calc

    caldata_fine = np.linspace(caldata.min(), caldata.max(), len(caldata) * 100)
    convdata_calc_fine = calibration.raw2data(caldata_fine)

    #
    ax = figure.add_subplot(3, 1, 1)
    ax.clear()
    ax.plot(convdata_calc_fine, caldata_fine, "-")
    ax.plot(refdata, caldata, "o")
    caltitle = "Calibration data of sn:{}".format(calibration.sn)
    xlabel = "{} [{}]".format(refchannel, calibration.unit)
    ylabel = "{}\n{} [{}]".format(calibration.sn, channel, calibration.unit_input)

    #ax.set_title(caltitle)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.xaxis.set_label_position('top')  # Label at top
    ax.xaxis.tick_top()
    ax.grid(True)

    # Difference plot
    caldiff_title = "Difference between reference data and calculated values after calibration sn:{}".format(calibration.sn)
    difflabel = "$\Delta$x [{}]".format(calibration.unit)
    legstrdiff = "$\Delta${}: {}$_{{ref}}$ - {}$_{{coeff}}$".format(refchannel,refchannel,calibration.sn)
    ax2 = figure.add_subplot(3, 1, 2)
    ax2.clear()
    #ax2.set_title(caldiff_title)
    lpl = ax2.plot(refdata, convdata_diff, "o")

    ax2.legend((lpl),[legstrdiff])
    ax2.set_xlabel(xlabel)
    ax2.set_ylabel(difflabel)
    ax2.grid(True)

    # Plot the calculation formula
    try:
        calc_form = calibration.get_formula()
    except:
        calc_form = "unknown"

    try:
        calc_form_explicit = calibration.get_formula_explicit()
    except:
        calc_form_explicit = "unknown"

    #print("Calc form",calc_form)
    cal_form_title = "Calibration formula:\n\n"
    ax3 = figure.add_subplot(3, 1, 3)
    ax3.clear()
    ax3.text(0.5, 0.8, cal_form_title + calc_form, ha="center",va="top")
    #ax3.text(0.0,0.1,calc_form_explicit,ha="left")
    #
    ax3.grid(False)  # no Grid
    for spine in ax3.spines.values():
        spine.set_visible(False)  # no border
    ax3.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)

def write_report_pdf(calibrations, filename):
    # filename = 'test.pdf'
    doc = SimpleDocTemplate(filename, pagesize=A4)
    elements = []

    if isinstance(calibrations,list):
        pass
    else:
        calibrations = [calibrations]

    for ical,calibration in enumerate(calibrations):
        if ical > 0:
            elements.append(PageBreak())  # New page from second calibration onwards
        # Get the data ready
        try:
            refchannel = calibration.calibration_reference_data.channel.datakey
        except:
            refchannel = calibration.calibration_reference_data.channel

        try:
            channel = calibration.channel.datakey
        except:
            channel = calibration.channel

        styles = getSampleStyleSheet()

        # Title
        elements.append(Paragraph("Calibration report", styles["Title"]))
        elements.append(Paragraph("for {} (SN:{})".format(channel, calibration.sn), styles["Title"]))

        # Date
        dt = calibration.date
        datestr = dt.replace(microsecond=0).isoformat()
        elements.append(Paragraph("Date: {}".format(datestr), styles["Heading3"]))
        elements.append(Paragraph("UUID: {}".format(calibration.calibration_uuid), styles["Heading3"]))
        elements.append(Paragraph("ID: {}".format(calibration.calibration_id), styles["Heading3"]))
        elements.append(Paragraph("Comment: {}".format(calibration.comment), styles["Heading3"]))

        # Calibration plot
        fig = plt.Figure()
        fig.set_size_inches(figsize_report_plot)
        temp_plot = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        print("Writing to tmp file:{}".format(temp_plot.name))
        plot_calibration(calibration, fig)
        fig.savefig(temp_plot.name, dpi=300)
        elements.append(Spacer(1, 12))
        elements.append(Image(temp_plot.name, width=400, height=300))
        elements.append(Spacer(1, 12))

        # Table with the coefficients
        style_table = TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ])
        styles = getSampleStyleSheet()
        style_header = styles["Normal"]
        data = []
        data1 = []
        data2 = []
        for i, c in enumerate(list(calibration.coeff)[::-1]):  # Reverse
            cheader = Paragraph("c<sub>{}</sub>".format(i), style_header)
            data1.append(cheader)
            cstring = "{:e}".format(c)
            data2.append(cstring)

        data.append(data1)
        data.append(data2)
        table = Table(data)
        table.setStyle(style_table)
        elements.append(table)
        elements.append(Spacer(1, 12))
        # Table with the rawdata
        refdata = np.asarray(calibration.calibration_reference_data.data)
        caldata = np.asarray(calibration.calibration_data.data)
        data = [["Reference", "Calibration data"]]
        data.append([calibration.unit_input,calibration.unit])
        for i, d in enumerate(zip(refdata, caldata)):
            data.append(d)
        # caldata_table = np.asarray([refdata,caldata]).tolist()
        # data[0].append(caldata_table)
        print("data for the table", data)
        table = Table(data)
        table.setStyle(style_table)
        elements.append(table)

        # Create a new page and dump the original data as json:
        json_text = calibration.model_dump_json(indent=4)
        elements.append(PageBreak())  # ➜ Neue Seite

        #
        elements.append(Paragraph("Calibration data JSON:", styles["Heading2"]))
        elements.append(Paragraph(f"<pre>{json_text}</pre>", styles["Code"]))

    doc.build(elements)
    print(f"PDF saved into: {filename}")

