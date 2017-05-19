# CT data object
# A CT object contains a CT scan and OB and DF images.

import os, glob
import numpy as np
import imars3d as i3
import progressbar
from . import decorators as dec

class CT:

    """CT reconstruction
    
>>> ct = CT(...)
>>> ct.preprocess()
>>> ct.recon()

Intermediate results are saved as object variables

* gamma_filtered
* normalized
* cropped
* if_corrected
* tilt_corrected
* sigogram

Reults:

* reconstructed
* recon_RAR
"""

    def __init__(
            self, path, CT_subdir=None, CT_identifier=None,
            workdir='work', outdir='out', 
            parallel_preprocessing=True, parallel_nodes=None,
            clean_on_the_fly=False,
            vertical_range=None,
            ob_identifier=None, df_identifier=None,
            ob_files=None, df_files=None):
        self.path = path
        if CT_subdir is not None:
            # if ct is in a subdir, its name most likely the
            # whole subdir is just for ct and no OB/DF.
            # in that case we don't usually need CT_identifier
            self.CT_subdir = CT_subdir
            self.CT_identifier = CT_identifier or '*'
        else:
            # if CT is not in a subdir, it is most likely
            # the CT files are identified by string "CT"
            self.CT_subdir = '.'
            self.CT_identifier = CT_identifier or 'CT'
        self.ob_identifier = ob_identifier
        self.df_identifier = df_identifier
        self.ob_files = ob_files
        self.df_files = df_files
        # workdir
        if not os.path.exists(workdir):
            os.makedirs(workdir)
        self.workdir = workdir
        # outdir
        if not os.path.exists(outdir):
            os.makedirs(outdir)
        self.outdir = outdir
        # find data paths
        self.sniff()
        from . import io
        # dark field
        self.dfs = io.imageCollection(glob_pattern=self.DF_pattern, files=self.df_files, name="Dark Field")
        # open beam
        self.obs = io.imageCollection(glob_pattern=self.OB_pattern, files=self.ob_files, name="Open Beam")
        # ct
        angles = self.angles
        self.theta = angles * np.pi / 180.
        pattern = self.CT_pattern
        self.ct_series = io.ImageFileSeries(pattern, identifiers = angles, name = "CT")

        self.parallel_preprocessing = parallel_preprocessing
        self.parallel_nodes = parallel_nodes
        self.clean_on_the_fly = clean_on_the_fly
        self.vertical_range = vertical_range
        return


    @dec.timeit
    def preprocess(self, workdir=None, outdir=None):
        workdir = workdir or self.workdir
        outdir = outdir or self.outdir
        # get image objs
        dfs = self.dfs; obs = self.obs
        ct_series = self.ct_series
        theta = self.theta
        # preprocess
        gamma_filtered = i3.gamma_filter(
            ct_series, workdir=os.path.join(workdir, 'gamma-filter'),
            parallel = self.parallel_preprocessing)
        normalized = i3.normalize(gamma_filtered, dfs, obs, workdir=os.path.join(workdir, 'normalization'))
        if self.clean_on_the_fly:
            gamma_filtered.removeAll()
        # save references
        self.gamma_filtered = gamma_filtered
        self.normalized = normalized
        return normalized


    def recon(self, workdir=None, outdir=None, tilt=None, crop_window=None,
              smooth_projection=None,
              **kwds):
        workdir = workdir or self.workdir;  outdir = outdir or self.outdir
        # preprocess
        pre = self.preprocess(workdir=workdir, outdir=outdir)
        # crop
        if crop_window is None:
            # auto-cropping
            cropped = self.autoCrop(pre)
        else:
            xmin, ymin, xmax, ymax = crop_window
            cropped = self.crop(
                pre, 
                left=xmin, right=xmax, top=ymin, bottom=ymax)
        if self.clean_on_the_fly:
            pre.removeAll()
        # median filter
        if smooth_projection:
            pre = smoothed = self.smooth(cropped, 3)
            self.smoothed_projection = smoothed
        else:
            pre = cropped
        # correct intensity fluctuation
        if_corrected = i3.correct_intensity_fluctuation(
            pre, workdir=os.path.join(workdir, 'intensity-fluctuation-correction'))
        if self.clean_on_the_fly:
            pre.removeAll()
        # correct tilt
        pre = if_corrected
        if tilt is None:
            tilt_corrected, tilt = self.correctTilt_loop(
                pre, workdir=workdir)
        else:
            tilt_corrected, tilt = i3.correct_tilt(
                pre, tilt=tilt, 
                workdir=os.path.join(workdir, 'tilt-correction' ),
                max_npairs=None, parallel=self.parallel_preprocessing)
        if self.clean_on_the_fly:
            pre.removeAll()
        #
        self.cropped = cropped
        self.if_corrected = if_corrected
        self.tilt_corrected = tilt_corrected
        # reconstruct
        self.reconstruct(tilt_corrected, workdir=workdir, outdir=outdir, **kwds)
        return


    def calculateTilt(self, workdir, calculator=None, image_series=None, **kwds):
        """calculate tilt

* workdir: working directory
* calculator: "direct" or "phasecorrelation"
* image_series: by default self.cropped
"""
        from . import tilt
        if calculator == 'direct':
            calculator = tilt.direct.DirectMinimization()
        elif calculator == 'phasecorrelation':
            calculator = tilt.phasecorrelation.PhaseCorrelation()
        if image_series is None:
            image_series = self.cropped
        return tilt._compute(image_series, workdir, calculator=calculator, **kwds)


    def removeRings(self, reconned=None, outfilename_template=None, **kwds):
        import tomopy
        # input
        if reconned is None: reconned = self.reconstructed
        # output
        outfilename_template = outfilename_template or "RAR_%i.tiff"
        from . import io
        corrected_ifs = io.ImageFileSeries(
            os.path.join(self.outdir, outfilename_template),
            identifiers = reconned.identifiers,
            name = "Ring-artifact-removed reconstruction", mode = 'w',
        )
        # process in chunks
        N = len(reconned)
        step = 100
        for istep in range(N//step+1):
            start = step*istep; end = step*(istep+1)
            if end > N: end = N
            if end <=start: continue
            # build array
            stack = np.array([im.data for im in reconned[start:end]])
            corrected = tomopy.remove_ring(stack, **kwds)
            for i in range(corrected.shape[0]):
                img = corrected_ifs[istep*step+i]
                img.data = corrected[i]
                img.save()
                continue
            continue
        self.recon_RAR = corrected_ifs
        return self.recon_RAR
            

    def correctTilt_loop(self, pre, workdir):
        # correct tilt
        MAX_TILT_ALLOWED = 0.05
        NROUNDS = 3
        for i in range(NROUNDS):
            tilt_corrected, tilt = i3.correct_tilt(
                pre, workdir=os.path.join(workdir, 'tilt-correction-%s' % i),
                max_npairs=None, parallel=self.parallel_preprocessing)
            if self.clean_on_the_fly:
                pre.removeAll()
            if abs(tilt) < MAX_TILT_ALLOWED: break
            pre = tilt_corrected
            continue
        if abs(tilt) >= MAX_TILT_ALLOWED:
            msg = "failed to bring tilt down to less than %s degrees in %s rounds" % (MAX_TILT_ALLOWED, NROUNDS)
            # raise RuntimeError(msg)
            import warnings
            warnings.warn(msg)
        return tilt_corrected, tilt

    @dec.timeit
    def autoCrop(self, series):
        # estimate average
        ave = self.estimateAverage(series)
        from . import io
        def save(d, p): 
            im = io.ImageFile(p); im.data = d; im.save()
        save(ave, "estimate-ave.tiff")
        # smooth it
        from scipy import ndimage 
        sm = ndimage.median_filter(ave, 9)
        save(sm, "sm-estimate-ave.tiff")
        # find foreground rectangle
        Y, X = np.where(sm < 0.8)
        ymax = Y.max(); ymin = Y.min()
        xmax = X.max(); xmin = X.min()
        # expand it a bit
        width = xmax - xmin; height = ymax - ymin
        xmin -= width/6.; xmax += width/6.
        ymin -= height/6.; ymax += height/6.
        HEIGHT, WIDTH = ave.shape
        if xmin < 0: xmin = 0
        if xmax > WIDTH-1: xmax =WIDTH-1
        if ymin < 0: ymin = 0
        if ymax > HEIGHT-1: ymax =HEIGHT-1
        # crop
        return self.crop(series, left=xmin, right=xmax, top=ymin, bottom=ymax)


    def estimateAverage(self, series):
        sum = None; N = 0
        for i,img in enumerate(series):
            if i%5!=0: continue # skip some
            data = img.data
            if sum is None:
                sum = np.array(data, dtype='float32')
            else:
                sum += data
            N += 1
            continue
        return sum/N


    def crop(self, series, left=None, right=None, top=None, bottom=None):
        Y,X = self.ct_series[0].data.shape
        left = left or 0
        right = right or X
        top = top or 0
        bottom = bottom or Y
        box = left, right, top, bottom
        from . import crop
        return crop(
            series, workdir=os.path.join(self.workdir, 'crop'), box=box,
            parallel = self.parallel_preprocessing)


    @dec.timeit
    def smooth(self, series, size=None):
        from . import smooth
        return smooth(
            series, workdir=os.path.join(self.workdir, 'smoothed'), size=size,
            parallel = self.parallel_preprocessing)


    @dec.timeit
    def reconstruct(
            self, 
            ct_series, workdir=None, outdir=None,
            rot_center=None, explore_rot_center=True,
            outfilename_template=None,
            **kwds):
        workdir = workdir or self.workdir;  
        outdir = outdir or self.outdir
        theta = self.theta
        # preprocess
        angles, sinograms = i3.build_sinograms(
            ct_series, workdir=os.path.join(workdir, 'sinogram'),
            parallel = self.parallel_preprocessing,
            parallel_nodes = self.parallel_nodes)
        # take the middle part to calculate the center of rotation
        NSINO = len(sinograms)
        sino = [s.data for s in sinograms[NSINO//3: NSINO*2//3]]
        # sino = [s.data for s in sinograms]
        sino= np.array(sino)
        proj = np.swapaxes(sino, 0, 1)
        import tomopy
        X = proj.shape[-1]
        DEVIATION = 40 # max deviation of rot center from center of image
        if explore_rot_center:
            print("* Exploring rotation center using tomopy...")
            tomopy.write_center(
                proj.copy(), theta,
                cen_range=[X//2-DEVIATION, X//2+DEVIATION, 1.],
                dpath=os.path.join(workdir, 'tomopy-findcenter'),
                emission=False)
        if rot_center is None:
            print("* Computing rotation center using 180deg pairs...")
            from .tilt import find_rot_center
            rot_center = find_rot_center.find(
                ct_series, workdir=os.path.join(workdir, 'find-rot-center'))
        print('* Rotation center: %s' % rot_center)
        open(os.path.join(workdir, 'rot_center'), 'wt').write(str(rot_center))
        # reconstruct 
        if self.vertical_range:
            sinograms = sinograms[self.vertical_range]
        self.sinograms = sinograms
        recon = i3.reconstruct(
            angles, sinograms, 
            workdir=outdir, filename_template=outfilename_template,
            center=rot_center,
            nodes=self.parallel_nodes,
            **kwds)
        self.reconstructed = recon
        return recon


    def sniff(self):
        if not self.ob_files:
            self.find_OB()
            print(" * found OB pattern: %s" % self.OB_pattern)
        else:
            self.OB_pattern = None
        if not self.df_files:
            self.find_DF()
            print(" * found DF pattern: %s" % self.DF_pattern)
        else:
            self.DF_pattern = None
        self.find_CT()
        print(" * found CT pattern: %s" % self.CT_pattern)
        return
        
    CT_pattern_cache = "CT_PATTERN"
    CT_angles_cache = "CT_ANGLES.npy"
    def find_CT(self):
        pattern_cache_path = os.path.join(self.workdir, self.CT_pattern_cache)
        angles_cache_path = os.path.join(self.workdir, self.CT_angles_cache)
        if os.path.exists(pattern_cache_path) and os.path.exists(angles_cache_path):
            self.CT_pattern = open(pattern_cache_path, 'rt').read().strip()
            self.angles = np.load(angles_cache_path)
            return
        CT_identifier = self.CT_identifier
        subdir = os.path.join(self.path, self.CT_subdir)
        patterns = [
            '*%s*_*_*.*' % CT_identifier,
            '*_*_*.*',
            ]
        found = None
        for pattern in patterns:
            files = glob.glob(os.path.join(subdir, pattern))
            if len(files):
                found = pattern
                break
            continue
        if not found:
            raise RuntimeError(
                "failed to find CT images. directory: %s, patterns tried: %s"%(
                    subdir, patterns)
                )
        re_pattern = '(\S+)_(\d+)_(\d+)_(\d+).(\S+)'
        def fn2angle(fn):
            import re
            m = re.match(re_pattern, fn)
            return float('%s.%s' % (m.group(2), m.group(3)))
        fns = map(os.path.basename, files)
        angles = map(fn2angle, fns)
        angles = set(angles)
        angles = sorted(angles)
        assert len(angles) > 2, "too few angles"
        delta = angles[1] - angles[0]
        # make sure angles are spaced correctly
        expected = np.arange(angles[0], angles[-1]+delta/2., delta)
        if len(expected) != len(angles):
            missing = [a for a in expected if not np.isclose(a, angles).any()]
            if len(missing):
                msg = "Missing angles: %s.\nStart: %s, End: %s, Step: %s" % (
                    missing, expected[0], expected[-1], delta)
                raise RuntimeError(msg)
            # nothing is missing, we are good
            angles = expected
        else:
            condition = np.isclose(
                np.arange(angles[0], angles[-1]+delta/2., delta),
                np.array(angles)
                ).all()
            assert condition, "angles not spaced correctly: %s" % (angles,)
        self.angles = np.array(angles) # in degrees
        printf_pattern_candidates = [
            "*%s" % CT_identifier + "*_%07.3f_*.*",
            "*%s" % CT_identifier + "*_%.3f_*.*",
            ]
        found = None
        for c in printf_pattern_candidates:
            from .ImageFileSeries import ImageFileSeries
            c = os.path.join(subdir, c)
            ifs = ImageFileSeries(c, angles)
            bad = False
            # progress bar
            bar = progressbar.ProgressBar(
                widgets=[
                    "Checking CT fn pattern",
                    progressbar.Percentage(),
                    progressbar.Bar(),
                    ' [', progressbar.ETA(), '] ',
                ],
                max_value = len(angles) - 1
            )
            for i, angle in enumerate(angles):
                try:
                    ifs.getFilename(angle)
                except:
                    import traceback as tb
                    tb.print_exc()
                    bad = True
                    break
                bar.update(i)
                continue
            if not bad:
                found = c
                break
            continue
        if not found:
            raise RuntimeError("Failed to find printf pattern. Filename: %s" %(
                fns[0]))
        self.CT_pattern = found
        open(pattern_cache_path, 'wt').write(found)
        np.save(angles_cache_path, self.angles)
        return

    
    def find_OB(self):
        if self.ob_identifier:
            fnp = ['*%s*' % self.ob_identifier]
        else:
            fnp = ['*ob*', '*OB*']
        return self._find_pattern(
            'OB',
            subdir_candidates = ['ob', 'OB'],
            filenamepattern_candidates = fnp,
            )

    def find_DF(self):
        if self.df_identifier:
            fnp = ['*%s*' % self.df_identifier]
        else:
            fnp = ['*df*', '*DF*']
        return self._find_pattern(
            'DF',
            subdir_candidates = ['df', 'DF'],
            filenamepattern_candidates = fnp,
            )


    def _find_pattern(self, kind, subdir_candidates, filenamepattern_candidates):
        candidates = subdir_candidates
        found = None
        for c in candidates:
            p = os.path.join(self.path, c)
            if os.path.exists(p):
                found = c; break
            continue
        if not found:
            # fall back is no subdir
            found = '.'
        setattr(self, '%s_subdir' % kind, found)
        subdir = found
        candidates = filenamepattern_candidates
        found = None
        for c in candidates:
            pattern = os.path.join(self.path, subdir, c)
            files = glob.glob(pattern)
            if files:
                found = pattern; break
            continue
        if not found:
            raise IOError("failed to find %s. patterns tried: %s" % (
                kind, filenamepattern_candidates))
        setattr(self, '%s_pattern' % kind, found)
        return

    pass


def get_ct_scan_info(files):
    re_pattern = '(\S+)_(\S+)_(\d+)_(\d+)_(\d+).(\S+)'
    def _(fn):
        import re
        m = re.match(re_pattern, fn)
        if not m: return
        angle = float('%s.%s' % (m.group(3), m.group(4)))
        date = m.group(1)
        name = m.group(2)
        return date, name, angle
    fns = map(os.path.basename, files)
    info = map(_, fns)
    return info

# End of file
