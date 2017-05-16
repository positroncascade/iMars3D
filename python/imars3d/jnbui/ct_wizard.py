# coding: utf-8

import os, imars3d, numpy as np, glob, time
import ipywidgets as ipyw
from IPython.display import display, HTML, clear_output
from ._utils import js_alert

class config:
    # object to hold inputs gathered from users
    ipts = None
    scan = None

class Panel:
    
    layout = ipyw.Layout(border="1px lightgray solid", margin='5px', padding='15px')
    button_layout = ipyw.Layout(margin='10px 5px 5px 5px')
    
    def show(self):
        display(self.panel)
        
    def remove(self):
        for w in self.widgets: w.close()
        self.panel.close()
        
    def nextStep(self):
        raise NotImplementedError
    

class WizardPanel:
    
    label_layout = ipyw.Layout(height='25px', padding='8px')
    
    def __init__(self, start_panel):
        display(ipyw.Label("Tomography reconstruction wizard", layout=self.label_layout))
        start_panel.show()
        return

    
class IPTSpanel(Panel):
    
    def __init__(self, config):
        self.config = config
        explanation = ipyw.Label("Please input your experiment IPTS number")
        self.text = ipyw.Text(value="", description="IPTS-", placeholder="IPTS number")
        self.ok = ipyw.Button(description='OK', layout=self.button_layout)
        self.widgets = [explanation, self.text, self.ok]
        self.ok.on_click(self.validate_IPTS)
        self.panel = ipyw.VBox(children=self.widgets, layout=self.layout)
        
    def validate_IPTS(self, s):
        ipts1 = self.text.value
        p = os.path.join('/HFIR/CG1D/IPTS-%s' % ipts1)
        if not os.path.exists(p):
            s = "Cannot open directory %s ! Please check IPTS number" % p
            js_alert(s)
        else:
            self.config.ipts = ipts = ipts1.encode()
            # use your experiment IPTS number
            self.config.iptsdir = iptsdir = "/HFIR/CG1DImaging/IPTS-%s/" % ipts
            # path to the directory with ct, ob, and df data files or subdirs
            datadir = self.config.datadir = os.path.join(iptsdir,"raw/")
            self.remove()
            # make sure there is ct scan directory
            self.config.ct_scan_root = ct_scan_root = os.path.join(datadir, 'ct_scans')
            ct_scan_subdirs = [d for d in os.listdir(ct_scan_root) if os.path.isdir(os.path.join(ct_scan_root, d))]
            self.config.ct_scan_subdirs = ct_scan_subdirs
            scan_panel = ScanNamePanel(self.config)
            scan_panel.show()
        return

class ScanNamePanel(Panel):
    def __init__(self, config):
        self.config = config
        explanation = ipyw.Label("Please give your neutron CT scan a name:")
        self.text = ipyw.Text(value="", description="Scan: ", placeholder="name of scan")
        self.ok = ipyw.Button(description='OK', layout=self.button_layout)
        self.widgets = [explanation, self.text, self.ok]
        self.ok.on_click(self.validate)
        self.panel = ipyw.VBox(children=self.widgets, layout=self.layout)
        
    def validate(self, s):
        v = self.text.value
        if not v:
            s = 'Please specify a name for your tomography scan'
            js_alert(s)
        else:
            self.config.scan = v.encode()
            self.remove()
            wd_panel = WorkDirPanel(self.config, self.config.scan)
            wd_panel.show()
        return

class SelectDirPanel(Panel):
    def __init__(self, initial_guess, explanation=""):
        self.createSelectDirPanel(initial_guess, explanation)
        self.createRemovalAlertPanel()
        
    def createSelectDirPanel(self, initial_guess, explanation):
        # panel for soliciting work dir name
        explanation_label = ipyw.Label(explanation)
        self.path_field = ipyw.Text(value=initial_guess)
        ok = ipyw.Button(description='OK', layout=self.button_layout)
        widgets = [explanation_label, self.path_field, ok]
        ok.on_click(self.validate)
        self.selectdir_panel = ipyw.VBox(children=widgets, layout=self.layout)
        
    def createRemovalAlertPanel(self):
        # panel for remove old dir
        alert = self.alert = ipyw.Label("** Warning: We are about to remove directory")
        self.pathtext = ipyw.Label("")
        self.alert_banner = ipyw.HBox(children=[self.alert, self.pathtext])
        layout=ipyw.Layout(width='240px', padding='10px')
        yes = ipyw.Button(description='Yes. Please remove the directory', layout=layout)
        no = ipyw.Button(description='No. Let me choose a different directory', layout=layout)
        yes.on_click(self.removeSelectedDir)
        no.on_click(self.askForDir)
        self.removalalert_panel = ipyw.VBox(children=[self.alert_banner, yes, no])
        return
    
    def removeSelectedDir(self, s):
        self.remove()
        wait = ipyw.HTML(value="<p>Removing. Please wait...</p>")
        display(wait); time.sleep(0.2)
        import shutil
        try:
            shutil.rmtree(self.path_candidate)
        except:
            wait.close()
            js_alert("Unable to remove directory tree %s" % self.path_candidate)
            self.askForDir(s)
            return
        wait.close()
        self.selected = self.path_candidate
        # print "seletecd: %s" % self.selected
        self.nextStep()
        return
    
    def askForDir(self, s):
        self.removalalert_panel.layout.display='none'
        self.selectdir_panel.layout.display='flex'
        return
        
    def show(self):
        display(self.selectdir_panel, self.removalalert_panel)
        self.removalalert_panel.layout.display='none'
        
    def remove(self):
        self.selectdir_panel.close()
        self.removalalert_panel.close()
        
    def compute_path_from_input(self):
        return self.path_field.value
    
    def validate(self, s):
        self.path_candidate = p = self.compute_path_from_input()
        if os.path.exists(p):
            # print "already exists"
            self.pathtext.value = '"%s"' % p
            self.removalalert_panel.layout.display='flex'
            self.selectdir_panel.layout.display='none'
        else:
            self.selected = p
            self.remove()
            # print "selected: %s" % self.selected
            self.nextStep()
        return

class WorkDirPanel(SelectDirPanel):
    def __init__(self, config, initial_guess):
        self.config = config
        # fast disk
        import getpass
        username = getpass.getuser()
        self.root = "/SNSlocal2/%s" % username
        explanation = "Please pick a name for your temporary working directory. Usually it is the same as the name of your CT scan. But you can use a different one if you want to. The directory will be created under %s" % self.root
        SelectDirPanel.__init__(self, initial_guess, explanation)
        self.path_field.description = 'Workdir: '
        self.path_field.placeholder = 'under %s' % self.root

    def compute_path_from_input(self):
        v = self.path_field.value
        return os.path.join(self.root, v)
    
    def nextStep(self):
        self.config.workdir = self.selected
        output_panel = OutputDirPanel(self.config, self.config.scan)
        output_panel.show()
        
        
class OutputDirPanel(SelectDirPanel):
    def __init__(self, config, initial_guess):
        self.config = config
        self.root = os.path.join(config.iptsdir, "shared/processed_data/")
        explanation = "Please pick a name for reconstruction output directory. Usually it is the same as the name of your CT scan. But you can use a different one if you want to. The directory will be created under %s" % self.root
        SelectDirPanel.__init__(self, initial_guess, explanation)
        self.path_field.description = 'Output dir: '
        self.path_field.placeholder = 'under %s' % self.root

    def compute_path_from_input(self):
        v = self.path_field.value
        return os.path.join(self.root, v)
    
    def nextStep(self):
        self.config.outdir = self.selected
        ctdir_panel = CTDirPanel(self.config)
        ctdir_panel.show()
    pass


class CTDirPanel(Panel):
    def __init__(self, config):
        self.config = config
        # by standard, ct directories must be inside IPTS/raw/ct_scans, but older IPTS may not conform
        # in that case, a general directory selector is used
        if not config.ct_scan_subdirs:
            return self.createDirSelector()
        # standard case
        explanation = ipyw.Label("Please choose the sub-directory that contains the image files for your CT scan")
        self.select = ipyw.Select(
            options=config.ct_scan_subdirs, value=config.ct_scan_subdirs[0], 
            description="CT scans")
        self.ok = ipyw.Button(description='Select', layout=self.button_layout)
        self.widgets = [explanation, self.select, self.ok]
        self.ok.on_click(self.validate)
        self.panel = ipyw.VBox(children=self.widgets, layout=self.layout)
        
    def validate(self, s):
        self.config.ct_subdir = self.select.value.encode()
        self.remove()
        self.nextStep()
        return
    
    def nextStep(self):
        next = CTSigPanel(self.config)
        next.show()
        return

    def createDirSelector(self):
        config = self.config
        # create file selector
        from .fileselector import FileSelectorPanel as FSP
        self.fsp = FSP("Please select the CT directory", start_dir=config.iptsdir, type='directory')
        # the call back function for the file selector
        def next():
            self.config.ct_subdir = self.fsp.selected
            self.nextStep()
            return
        self.fsp.next = next
        # show() method needs self.panel
        self.panel = self.fsp.panel
        return


class CTSigPanel(Panel):
    def __init__(self, config):
        self.config = config
        ct_sig, sample = self.calculate()
        explanation1 = ipyw.Label(
            "A signature word for filenames of the CT scan is needed.\n"
            +"The following is our best guess.\n")
        explanation2 = ipyw.Label(
            "If it does not work, please try to come up with a string that is common in all files of the CT scan of interests.\n"
            +"Here are some random samples of CT filenames:")
        samples = [ipyw.Label(s) for s in sample]
        sample_panel = ipyw.VBox(
            children=samples, 
            layout=ipyw.Layout(padding="20px", height='120px', width='600px', overflow_x='auto', overflow_y='auto')
        )
        self.text = ipyw.Text(value=ct_sig, description="CT signature", layout=ipyw.Layout(margin="20px"))
        self.ok = ipyw.Button(description='OK', layout=self.button_layout)
        self.widgets = [explanation1, self.text, explanation2, sample_panel, self.ok]
        self.ok.on_click(self.validate)
        self.panel = ipyw.VBox(children=self.widgets, layout=self.layout)
        
    def calculate(self):
        config = self.config
        # all files
        ct_dir = os.path.join(config.ct_scan_root, config.ct_subdir)
        ct_files = os.listdir(ct_dir)
        # assume all files start with date like 20160918
        files_without_dates = [f[9:] for f in ct_files]
        # find common prefix
        ct_sig0 = os.path.commonprefix(files_without_dates).strip()
        ct_sig = '_'.join(ct_sig0.split('_')[:-2])
        #  Example CT scan filenames
        indexes = np.random.choice(len(ct_files), 10)
        sample = [ct_files[i] for i in indexes]
        return ct_sig, sample
        
    def validate(self, s):
        self.config.ct_sig = self.text.value.encode()
        self.remove()
        self.nextStep()
        return
    
    def nextStep(self):
        next = OBPanel(self.config)
        next.show()
        return


class OBPanel(Panel):
    def __init__(self, config):
        self.config = config
        all_obs = self.calculate()
        # by standard, ob files must be inside IPTS/raw/OB, but older IPTS may not conform.
        # in that case, a general file selector is used
        if not all_obs:
            return self.createOBFilesSelector()
        # standard case
        explanation1 = ipyw.Label(
            "Open beam (OB) measurements are needed for normalization. "
            "Please select the OB files from below."
            "Use Shift-click or Ctrl-click to select multiple files"
            )
        self.select = ipyw.SelectMultiple(
            value=[], options=all_obs,
            description="OB files", 
            layout=ipyw.Layout(margin="20px", width="600px"))
        self.ok = ipyw.Button(description='OK', layout=self.button_layout)
        self.widgets = [explanation1, self.select, self.ok]
        self.ok.on_click(self.validate)
        self.panel = ipyw.VBox(children=self.widgets, layout=self.layout)
        
    def calculate(self):
        config = self.config
        # all files
        config.ob_dir = ob_dir = os.path.join(config.datadir, 'ob')
        exts = ['.fits', '.tif', '.tiff']
        files = []
        for f in os.listdir(ob_dir):
            b, ext = os.path.splitext(f)
            if ext in exts:
                files.append(f)
            continue
        return files
        
    def validate(self, s):
        v = [i.encode() for i in self.select.value]
        if not v:
            js_alert("Please select at least one OB file")
            return
        config = self.config
        config.ob_files = [os.path.join(config.ob_dir, f) for f in v]
        self.remove()
        self.nextStep()
        return
    
    def nextStep(self):
        next = DFPanel(self.config)
        next.show()
        return

    def createOBFilesSelector(self):
        config = self.config
        # create file selector
        from .fileselector import FileSelectorPanel as FSP
        self.fsp = FSP("OB files", start_dir=config.iptsdir, type='file', multiple=True)
        # call back function
        def next():
            self.config.ob_files = self.fsp.selected
            self.nextStep()
            return
        self.fsp.next = next
        # show() method need self.panel
        self.panel = self.fsp.panel
        return

    
class DFPanel(Panel):
    def __init__(self, config):
        self.config = config
        all_dfs = self.calculate()
        # by standard, df files must be inside IPTS/raw/DF, but older IPTS may not conform.
        # in that case, a general file selector is used
        if not all_dfs:
            return self.createDFFilesSelector()
        # standard case
        explanation1 = ipyw.Label(
            "Dark field (DF) measurements are needed for background correction. "
            "Please select the DF files from below. "
            "Use Shift-click or Ctrl-click to select multiple files"
            )
        self.select = ipyw.SelectMultiple(
            value=[], options=all_dfs,
            description="DF files", 
            layout=ipyw.Layout(margin="20px", width="600px"))
        self.ok = ipyw.Button(description='OK', layout=ipyw.Layout(margin="20px"))
        self.widgets = [explanation1, self.select, self.ok]
        self.ok.on_click(self.validate)
        self.panel = ipyw.VBox(children=self.widgets, layout=self.layout)
        
    def calculate(self):
        config = self.config
        # all files
        config.df_dir = df_dir = os.path.join(config.datadir, 'df')
        exts = ['.fits', '.tif', '.tiff']
        files = []
        for f in os.listdir(df_dir):
            b, ext = os.path.splitext(f)
            if ext in exts:
                # p = os.path.join(df_dir, f)
                # t = time.ctime(os.path.getmtime(p))
                # s = '%s: %s' % (f, t)
                # files.append(s)
                files.append(f)
            continue
        return files
        
    def validate(self, s):
        v = [i.encode() for i in self.select.value]
        if not v:
            js_alert("Please select at least one DF file")
            return
        config = self.config
        config.df_files = [os.path.join(config.df_dir, f) for f in v]
        self.remove()
        self.nextStep()
        return
    
    def nextStep(self):
        print "Configuration done!"
        return

    def createDFFilesSelector(self):
        config = self.config
        # create file selector
        from .fileselector import FileSelectorPanel as FSP
        self.fsp = FSP("DF files", start_dir=config.iptsdir, type='file', multiple=True)
        # call back function
        def next():
            self.config.df_files = self.fsp.selected
            self.nextStep()
            return
        self.fsp.next = next
        # show() method need self.panel
        self.panel = self.fsp.panel
        return

    
# WizardPanel(DFPanel(config))
# WizardPanel(IPTSpanel(config))