import sys
import numpy as np
import matplotlib.pyplot as plt
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QFileDialog, QVBoxLayout, QWidget, QSlider, QLabel, QHBoxLayout,QAction,QComboBox,QCheckBox,QDialog,QSpinBox,QGroupBox
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import pickle
# from mplcursors import cursor  # separate package must be installed
import matplotlib.colors as mcolors
import matplotlib as mpl

import xarray
import datetime
from dateutil.tz import tzutc
import time
from PIL import Image
import io

# mpl.style.use('seaborn-v0_8-paper')
plt.style.use('seaborn-v0_8-whitegrid')

plot_colors = list(mcolors.TABLEAU_COLORS.values())

SMALL_SIZE = 10
MEDIUM_SIZE = 12
BIGGER_SIZE = 14


plt.rc('font', size=SMALL_SIZE)          # controls default text sizes
plt.rc('axes', titlesize=MEDIUM_SIZE)     # fontsize of the axes title
plt.rc('axes', labelsize=SMALL_SIZE)    # fontsize of the x and y labels
plt.rc('xtick', labelsize=SMALL_SIZE)    # fontsize of the tick labels
plt.rc('ytick', labelsize=SMALL_SIZE)    # fontsize of the tick labels
plt.rc('legend', fontsize=SMALL_SIZE)    # legend fontsize
plt.rc('figure', titlesize=BIGGER_SIZE)  # fontsize of the figure title
plt.rcParams["font.weight"] = "bold"
plt.rcParams["axes.labelweight"] = "bold"
plt.rcParams['axes.titleweight'] = 'bold'

CLIP_MIN = -25
CLIP_MAX = 25

DAILY_SECONDS = 60*60*24
FIVE_MINUTES_S = 60*5
TIME_SPAN = DAILY_SECONDS//FIVE_MINUTES_S
N_ERRORS = 3

def dt64_to_datetime(date):
    """
    Converts a numpy datetime64 object to a python datetime object 
    Input:
      date - a np.datetime64 object
    Output:
      DATE - a python datetime object
    """
    timestamp = ((date - np.datetime64('1970-01-01T00:00:00'))
                 / np.timedelta64(1, 's'))
    # return datetime.datetime.utcfromtimestamp(timestamp)
    return datetime.datetime.fromtimestamp(timestamp,tz=tzutc())

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Data Plotter")
        # self.setGeometry(100, 100, 1200, 1200)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.layout_box = QHBoxLayout()

        self.figure, self.axes = plt.subplots(subplot_kw={'projection': 'polar'},figsize=(15,7))
        
        
        self.figure2, self.axes2 = plt.subplots(nrows=3,ncols=1,figsize=(15,7))

        self.figure2.tight_layout(pad=3.0)
        self.figure2.subplots_adjust(bottom=0.12,right=0.88)
        
        self.canvas = FigureCanvas(self.figure)
        # self.toolbar = NavigationToolbar(self.canvas, self)
        # self.toolbar.hide()
        self.annot = None
        self.cid = self.figure.canvas.mpl_connect('motion_notify_event', self.polar_hover)
        
        
        self.canvas2 = FigureCanvas(self.figure2)
        self.annot2 = None
        self.cid2 = self.figure2.canvas.mpl_connect('motion_notify_event', self.err_hover)
        # self.layout.addWidget(self.canvas)

        # self.cid3 = self.figure3.canvas.mpl_connect('motion_notify_event', self.err_hover)

        # Vertical Slider
        self.vertical_layout = QVBoxLayout()
        # self.layout.addLayout(self.vertical_layout)


        '''Sliders'''
        self.vertical_slider_label = QLabel(f"{45}°\nElevation")

        # self.vertical_layout.addWidget(self.vertical_slider_label)

        self.vertical_slider = QSlider(Qt.Vertical)
        self.vertical_slider.setMinimum(10)
        self.vertical_slider.setMaximum(90)
        self.vertical_slider.setTickInterval(1)
        self.vertical_slider.setValue(45)  # Initial value
        self.vertical_slider.valueChanged.connect(self.vertical_slider_changed)
        # self.vertical_layout.addWidget(self.vertical_slider)

        # Horizontal Slider
        self.horizontal_slider_label = QLabel(f"Time(s) 0, HH:MM 00:00")
        # self.layout.addWidget(self.horizontal_slider_label)

        self.horizontal_slider = QSlider(Qt.Horizontal)
        self.horizontal_slider.setMinimum(0)
        self.horizontal_slider.setMaximum(TIME_SPAN-1)
        self.horizontal_slider.setTickInterval(1)
        self.horizontal_slider.setValue(0)  # Initial value
        self.horizontal_slider.valueChanged.connect(self.horizontal_slider_changed)


        self.vertical_layout_combobox = QVBoxLayout()
        self.vertical_layout_combobox.setAlignment(Qt.AlignTop)

        
        '''Years'''

        self.year_dropdown = QComboBox(self)
        self.year_dropdown.currentIndexChanged.connect(self.dropdown_update)
        self.vertical_layout_combobox.addWidget(QLabel("Year"))
        self.vertical_layout_combobox.addWidget(self.year_dropdown)

        # self.dropdown2 = QComboBox(self)
        # self.dropdown2.currentIndexChanged.connect(self.dropdown_update)
        # self.vertical_layout_combobox.addWidget(QLabel("Agency"))
        # self.vertical_layout_combobox.addWidget(self.dropdown2)

        # self.vertical_layout_combobox.addWidget(self.legend_checkbox)

        '''Add layout for Checkboxes'''
        self.layout_checkboxes = QVBoxLayout()
        self.vertical_layout_combobox.addLayout(self.layout_checkboxes)


        '''Heatmaps section'''
        groupbox_heatmaps = QGroupBox("Heatmaps")
        groupbox_heatmaps_layout = QVBoxLayout()
        groupbox_heatmaps.setLayout(groupbox_heatmaps_layout)

        self.show_popup_button = QPushButton("Show", self)
        self.show_popup_button.clicked.connect(self.show_popup)
        # self.vertical_layout_combobox.addWidget(QLabel("Heatmaps:"))

        self.clip_spinbox = QSpinBox()
        self.clip_spinbox.setValue(CLIP_MAX)
        # self.vertical_layout_combobox.addWidget(QLabel("Clip value(m):"))
        groupbox_heatmaps_layout.addWidget(QLabel("Clip value(m):"))
        # self.vertical_layout_combobox.addWidget(self.clip_spinbox)
        groupbox_heatmaps_layout.addWidget(self.clip_spinbox)
        # self.vertical_layout_combobox.addWidget(self.show_popup_button)



        self.correlation_dropdown = QComboBox(self)
        self.correlation_dropdown.addItems(list(f'{i}' for i in range(0,7+1)))
        self.correlation_dropdown.currentIndexChanged.connect(self.dropdown_update)
        # self.vertical_layout_combobox.addWidget(QLabel("Correlation(days):"))
        groupbox_heatmaps_layout.addWidget(QLabel("Correlation(days):"))
        # self.vertical_layout_combobox.addWidget(self.dropdown3)
        groupbox_heatmaps_layout.addWidget(self.correlation_dropdown)
        groupbox_heatmaps_layout.addWidget(self.show_popup_button)

        self.vertical_layout_combobox.addWidget(groupbox_heatmaps)


        '''Save Figure'''

        self.save_button = QPushButton("Save", self)
        self.save_button.clicked.connect(self.save_figure)
        self.vertical_layout_combobox.addWidget(QLabel("Figure:"))
        self.vertical_layout_combobox.addWidget(self.save_button)



        '''Final Layouts'''
        self.layout_box.addWidget(self.vertical_slider)
        self.layout_box.addWidget(self.vertical_slider_label)

        self.vertical_layout.addWidget(self.canvas)
        self.vertical_layout.addWidget(self.horizontal_slider)
        self.vertical_layout.addWidget(self.horizontal_slider_label)

        self.layout_box.addLayout(self.vertical_layout)
        self.layout_box.addLayout(self.vertical_layout_combobox)

        self.layout.addLayout(self.layout_box)
        self.layout.addWidget(NavigationToolbar(self.canvas2, self))
        self.layout.addWidget(self.canvas2)
        # self.layout.addWidget(self.canvas3)


        self.data = None
        self.data_array = None

        self.create_menu()
        self.create_data()

    def create_data(self):
        self.theta = np.linspace(0,2*np.pi,100)
        self.cossin = np.vstack((np.cos(self.theta),np.sin(self.theta)))
        # print(self.cossin.shape)

    def create_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu('File')

        load_file_action = QAction('Load File', self)
        load_file_action.triggered.connect(self.load_file)
        file_menu.addAction(load_file_action)
    
    def init_checkboxes(self,agencies):
        # print(self.layout_checkboxes.count())
        for i in reversed(range(self.layout_checkboxes.count())): 
            # self.layout_checkboxes.itemAt(i).widget().setParent(None)
            self.layout_checkboxes.itemAt(i).widget().deleteLater()

        # self.layout_checkboxes.addWidget(QLabel("Compare:"))
        for agency in agencies:
            checkbox = QCheckBox(agency)
            self.layout_checkboxes.addWidget(checkbox)
            checkbox.stateChanged.connect(self.checkbox_on_change)
            if agency == 'igs':checkbox.setChecked(True) 
            
        

    def polar_hover(self, event):

        if event.inaxes == self.axes:
            x, y = event.xdata, event.ydata
            if self.annot:
                self.annot.remove()
            self.annot = self.axes.annotate(f'Azimuth: {np.rad2deg(x):.1f}\ndH(m): {y:.2f}',
                                           xy=(x, y), xycoords='data',
                                           xytext=(-20, 20), textcoords='offset points',
                                           bbox=dict(boxstyle="round", fc="w"),
                                           arrowprops=dict(arrowstyle="->"))
            
            self.canvas.draw_idle()

    def get_checked_agencies(self):
        agencies = []
        for i in range(self.layout_checkboxes.count()):
            c = self.layout_checkboxes.itemAt(i).widget()
            if not c.isChecked(): continue
            keyAgency = c.text()
            agencies.append(keyAgency)

        return agencies

    def checkbox_on_change(self,value):

        self.plot_data(self.horizontal_slider.value(), self.vertical_slider.value())

        # checkbox = self.sender()
        # print(checkbox.text())
        # print(value)

        for i in range(self.layout_checkboxes.count()):
            c = self.layout_checkboxes.itemAt(i).widget()
            # if not isinstance(c,QLabel):
                # print(c.isChecked())
            if c.isChecked(): 
                pass
                # print(c.text())

    def err_hover(self, event):

        if event.inaxes == self.axes2[0]:
            x, y = event.xdata, event.ydata
            if self.annot2:
                self.annot2.remove()
            self.annot2 = self.axes2[0].annotate(f'seconds: {x:.0f}\nmeters: {y:.2f}',
                                           xy=(x, y), xycoords='data',
                                           xytext=(-20, 20), textcoords='offset points',
                                           bbox=dict(boxstyle="round", fc="w"),
                                           arrowprops=dict(arrowstyle="->"))
            self.canvas2.draw_idle()

        if event.inaxes == self.axes2[1]:
            x, y = event.xdata, event.ydata
            if self.annot2:
                self.annot2.remove()
            self.annot2 = self.axes2[1].annotate(f'seconds: {x:.0f}\nmeters: {y:.2f}',
                                           xy=(x, y), xycoords='data',
                                           xytext=(-20, 20), textcoords='offset points',
                                           bbox=dict(boxstyle="round", fc="w"),
                                           arrowprops=dict(arrowstyle="->"))
            
            self.canvas2.draw_idle()


        if event.inaxes == self.axes2[2]:       
            x, y = event.xdata, event.ydata
            if self.annot2:
                self.annot2.remove()
            self.annot2 = self.axes2[2].annotate(f'seconds: {x:.0f}\nmeters: {y:.2f}',
                                           xy=(x, y), xycoords='data',
                                           xytext=(-20, 20), textcoords='offset points',
                                           bbox=dict(boxstyle="round", fc="w"),
                                           arrowprops=dict(arrowstyle="->"))
            self.canvas2.draw_idle()

    def load_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        # file_name, _ = QFileDialog.getOpenFileName(self, "Load Data File","Pickle Files (*.pickle)", options=options)
        file_name, _ = QFileDialog.getOpenFileName(self, "Open netCDF File", "./netCDF", "netCDF Files (*.nc)", options=options)
        if file_name:
            try:
                self.data_array = xarray.open_dataarray(file_name)
                # print(self.data_array)
            except Exception as e:
                print(e) 

            years = sorted(set([f'{dt64_to_datetime(dt64).year}' for dt64 in self.data_array.coords['date'].data]))
            self.year_dropdown.addItems(years)

            agencies = [a for a in self.data_array.coords['agency'].data]
            # self.dropdown2.addItems(agencies)

            self.init_checkboxes(agencies)

    def save_figure(self):
        if self.data_array is None: return

        keyYear = int(self.year_dropdown.currentText())
        # keyAgency = self.dropdown2.currentText()

        # for keyAgency in self.get_checked_agencies():

        file_name = time.strftime(f"Elevation_{keyYear}_{'_'.join(self.get_checked_agencies())}_{self.data_array.name}_%Y%m%d_%H%M%S") + ".png"
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Figure", file_name, "PNG (*.png);;All Files (*)")
        if file_path:

            img_buf_top = io.BytesIO()
            img_buf_bot = io.BytesIO()

            self.figure.savefig(img_buf_top,format='png')
            self.figure2.savefig(img_buf_bot,format='png')
    
            im_top = Image.open(img_buf_top)
            im_bot = Image.open(img_buf_bot)
            images = [im_top,im_bot]

            widths, heights = zip(*(i.size for i in images))

            max_width = max(widths)
            total_height = sum(heights)

            new_im = Image.new('RGB', (max_width, total_height))

            x_offset = 0
            for im in images:
                new_im.paste(im, (0,x_offset))
                x_offset += im.size[1]
            
            new_im.save(file_name)

            img_buf_top.close() 
            img_buf_bot.close()

    def plot_data(self, horizontal_slider_value, vertical_slider_value):

        # print(self.data)
        if self.data_array is not None:

            keyYear = int(self.year_dropdown.currentText())
            # keyAgency = self.dropdown2.currentText()
            self.axes.clear()
            for a in self.axes2:
                a.clear()
            # self.axes2[0].clear()
            # self.axes2[1].clear()
            # self.axes2[2].clear()

            for agency_index,keyAgency in enumerate(self.get_checked_agencies()):

                yearly_dataarray = self.data_array.sel(date=self.data_array['date'].dt.year.isin([keyYear]))

                # xy_err = yearly_dataarray.loc[keyAgency,['north','east']].mean('date').data
                # xy_std = yearly_dataarray.loc[keyAgency,['north','east']].std('date').data

                # z_err = yearly_dataarray.loc[keyAgency,'up'].mean('date').data
                # z_std = yearly_dataarray.loc[keyAgency,'up'].std('date').data

                xy_err = yearly_dataarray.loc[keyAgency,['north','east']].interpolate_na(dim="time(s)", method="linear").mean('date').data
                xy_var = yearly_dataarray.loc[keyAgency,['north','east']].interpolate_na(dim="time(s)", method="linear").var('date').data

                xy_err_original = yearly_dataarray.loc[keyAgency,['north','east']].mean('date').data

                z_err = yearly_dataarray.loc[keyAgency,'up'].interpolate_na(dim="time(s)", method="linear").mean('date').data
                z_var = yearly_dataarray.loc[keyAgency,'up'].interpolate_na(dim="time(s)", method="linear").var('date').data

                z_err_original = yearly_dataarray.loc[keyAgency,'up'].mean('date').data
                

                # print(yearly_dataarray.loc[keyAgency,'up'].data)

                
                # xy_err = self.data[[0,2],:]
                # xy_std = self.data[[1,3],:]

                xy_upp = xy_err + 2*xy_var**.5
                xy_low = xy_err - 2*xy_var**.5
                z_upp = z_err + 2*z_var**.5
                z_low = z_err - 2*z_var**.5

                '''Polar plot'''
                def project_xy_error(north_east_arr):
                    arr_t = north_east_arr.transpose((1,0,-1))
                    trigo = np.repeat(np.expand_dims(self.cossin.T,axis=0),arr_t.shape[0],axis=0)
                    _prod = -(trigo @ arr_t)
                    _mean = np.mean(_prod,axis=0)
                    _var = np.var(_prod,axis=0)
                    return _prod,_mean,_var
                
                north_east_arr = yearly_dataarray.loc[keyAgency,['north','east']].interpolate_na(dim="time(s)", method="linear",fill_value="extrapolate").data
                _prod,_mean,_var = project_xy_error(north_east_arr)

                polar_mean = (_mean+z_err)#[:,horizontal_slider_value]
                polar_std = np.sqrt(_var+z_var)
                polar_upp = (polar_mean + 2*polar_std)[:,horizontal_slider_value]
                polar_low = (polar_mean - 2*polar_std)[:,horizontal_slider_value]
                polar_mean = polar_mean[:,horizontal_slider_value]

                polar_mean_h_proj = np.tan(vertical_slider_value/180 * np.pi)*polar_mean
                polar_upp_h_proj  = np.tan(vertical_slider_value/180 * np.pi)*polar_upp
                polar_low_h_proj  = np.tan(vertical_slider_value/180 * np.pi)*polar_low

                # print(polar_mean[:3] )
                # print(polar_upp [:3] )
                # print(polar_low [:3] )

                # print('************************')


                # polar_mean = -(self.cossin.T @ xy_err)[:,horizontal_slider_value] + z_err[horizontal_slider_value]
                # polar_upp =  -(self.cossin.T @ xy_upp)[:,horizontal_slider_value] + z_upp[horizontal_slider_value]
                # polar_low =  -(self.cossin.T @ xy_low)[:,horizontal_slider_value] + z_low[horizontal_slider_value]


                # print(self.cossin.shape,yearly_dataarray.loc[keyAgency,['north','east']].shape)

                self.axes.plot(self.theta,polar_mean_h_proj,label=f'{keyAgency.upper()} μ : total error H(m)')
                # self.axes.plot(self.theta,np.tan(vertical_slider_value/180 * np.pi)*polar_upp,c='r')
                # self.axes.plot(self.theta,np.tan(vertical_slider_value/180 * np.pi)*polar_low,c='b')
                # self.axes.set_yticks(np.linspace(-2,3,6))
                # self.axes.set_rticks(np.linspace(-2,3,16))
                self.axes.fill_between(self.theta,polar_upp_h_proj,polar_low_h_proj,alpha=0.2,label=f'{keyAgency.upper()} 2σ : total error H(m)')
                self.axes.set_title(f'Station : {self.data_array.name},(North,East)->Total Height error(m)')
                # self.axes.legend(bbox_to_anchor=(1.05, 0.5, 0.5, 0.5))
                self.axes.legend(bbox_to_anchor=(-.6, 0.5, 0.5, 0.5))

                '''Errors plot'''

                time_span = np.linspace(FIVE_MINUTES_S,DAILY_SECONDS,TIME_SPAN)

                self.axes2[0].plot(time_span,xy_err[1,:],label=f'{keyAgency.upper()} interpolated',c=plot_colors[agency_index])
                self.axes2[1].plot(time_span,xy_err[0,:],label=f'{keyAgency.upper()} interpolated',c=plot_colors[agency_index])
                self.axes2[2].plot(time_span,z_err,label=f'{keyAgency.upper()} interpolated',c=plot_colors[agency_index])


                self.axes2[0].set_title('North')
                self.axes2[1].set_title('East')
                self.axes2[2].set_title('Up')

                self.axes2[0].set_ylabel('Error(m)')
                self.axes2[1].set_ylabel('Error(m)')
                self.axes2[2].set_ylabel('Error(m)')
                # self.axes2[0].set_xlabel('Time(s)')
                # self.axes2[1].set_xlabel('Time(s)')
                self.axes2[2].set_xlabel('Time(s)')

                self.axes2[0].fill_between(time_span,xy_upp[1,:],xy_low[1,:],alpha=0.4,color=plot_colors[agency_index])
                self.axes2[1].fill_between(time_span,xy_upp[0,:],xy_low[0,:],alpha=0.4,color=plot_colors[agency_index])
                self.axes2[2].fill_between(time_span,z_upp,z_low,alpha=0.4,color=plot_colors[agency_index])

                self.axes2[0].scatter(time_span,xy_err_original[1,:],label=f'{keyAgency.upper()}',c=plot_colors[agency_index],s=5)
                self.axes2[1].scatter(time_span,xy_err_original[0,:],label=f'{keyAgency.upper()}',c=plot_colors[agency_index],s=5)
                self.axes2[2].scatter(time_span,z_err_original,label=f'{keyAgency.upper()}',c=plot_colors[agency_index],s=5)

                self.axes2[0].legend(bbox_to_anchor=(.62, 0.7, 0.5, 0.5))
                self.axes2[1].legend(bbox_to_anchor=(.62, 0.7, 0.5, 0.5))
                self.axes2[2].legend(bbox_to_anchor=(.62, 0.7, 0.5, 0.5))

                vline_x = (horizontal_slider_value+1)*300
                self.axes2[0].axvline(x=vline_x,ymin=0,ymax=1,c='r')
                self.axes2[1].axvline(x=vline_x,ymin=0,ymax=1,c='r')
                self.axes2[2].axvline(x=vline_x,ymin=0,ymax=1,c='r')

                # self.axes2[0].grid()
                # self.axes2[1].grid()
                # self.axes2[2].grid()

            self.canvas.draw()
            self.canvas2.draw()

    def vertical_slider_changed(self, value):
        self.vertical_slider_label.setText(f"{value}°\nElevation")
        self.plot_data(self.horizontal_slider.value(), value)

    def horizontal_slider_changed(self, value):
        seconds = (value+1)*300
        hours = '{:02d}'.format(seconds//3600)
        minutes = '{:02d}'.format((seconds//60)%60)
        self.horizontal_slider_label.setText(f"Time(s) {(value+1)*300}, HH:MM {hours}:{minutes}")
        self.plot_data(value, self.vertical_slider.value())

    def dropdown_update(self,value):

        keyYear = self.year_dropdown.currentText()
        # keyAgency = self.dropdown2.currentText()
        if keyYear: 
            self.plot_data(self.horizontal_slider.value(), self.vertical_slider.value())
            
    def show_popup(self):


        for keyAgency in self.get_checked_agencies():

            def save_figure():
                file_name = time.strftime(f"Heatmap_{keyYear}_{keyAgency}_{self.data_array.name}_%Y%m%d_%H%M%S") + ".png"
                file_path, _ = QFileDialog.getSaveFileName(self, "Save Figure", file_name, "PNG (*.png);;All Files (*)")
                if file_path:
                    figure3.savefig(file_path)


            popup = QDialog(self)
            popup.setWindowTitle("Heatmaps")
            # popup.setGeometry(200, 200, 600, 400)
            figure3, axes3 = plt.subplots(nrows=3,ncols=1,figsize=(12,16))
            # figure3.tight_layout()
            figure3.tight_layout(pad=6.0)
            figure3.subplots_adjust(top=0.92, right=1.05)

            canvas3 = FigureCanvas(figure3)
            annot3 = None

            save_button = QPushButton("Save Figure", self)
            save_button.clicked.connect(save_figure)
            
            layout = QVBoxLayout()
            popup.setLayout(layout)
            layout.addWidget(NavigationToolbar(canvas3, self))
            layout.addWidget(canvas3)

            if self.data_array is not None:

                layout.addWidget(save_button)
                keyYear = int(self.year_dropdown.currentText())
                # keyAgency = self.dropdown2.currentText()
                clip_value = int(self.clip_spinbox.value())
                shift = int(self.correlation_dropdown.currentText())


                yearly_dataarray = self.data_array.sel(date=self.data_array['date'].dt.year.isin([keyYear]))#.where((self.data_array > -clip_value) & (self.data_array < clip_value))#.clip(-5,5)



                figure3.suptitle(f"{keyAgency.upper()} heatmap, correletion {shift}(days)",weight='bold')
                
                for i,err in enumerate(yearly_dataarray.coords['error'].data):
                    if shift:
                        a = yearly_dataarray.loc[keyAgency,err]
                        b = yearly_dataarray.loc[keyAgency,err].shift(date=shift)
                        (b-a).clip(-clip_value,clip_value).plot(ax=axes3[i],cmap='inferno',cbar_kwargs={'label': "meters"})
                        # yearly_dataarray.loc[keyAgency,err]#.plot(ax=axes3[i],cmap='inferno',cbar_kwargs={'label': "meters"})

                        # (data_array[0,0].shift(date=-700) - data_array[0,0]).clip(-5,5).dropna(dim='date',how='any').plot(cmap='inferno')
                    else:
                        yearly_dataarray.loc[keyAgency,err].clip(-clip_value,clip_value).plot(ax=axes3[i],cmap='inferno',cbar_kwargs={'label': "meters"})

                    # print(axes3[i].title)

            popup.exec_()

    
    


if __name__ == '__main__':
    app = QApplication(sys.argv)
    globalFont = QFont('Arial', SMALL_SIZE)
    globalFont.setBold(True)
    app.setFont(globalFont)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())
