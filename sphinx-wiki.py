#!/usr/bin/env python
"""
License: 3-clause (new) BSD license, http://en.wikipedia.org/wiki/BSD_license
Copyright: Kevin Dunn, 2010.

INSTALLATION
------------

We presume your wiki is located on the server at:   /var/www/wiki

1.  Create a directory for this extension:
        mkdir -p /var/www/wiki/extensions/sphinx-wiki

2.  Clone the source code into this extension directory:
        cd /var/www/wiki/extensions/
        hg clone http://bitbucket.org/kevindunn/sphinx-wiki sphinx-wiki

3.  Install the Python library ``wikitools`` that interacts with Mediawiki
        easy_install -U wikitools

4.  Change the settings below to match your server settings and preferences.
    You may need to create directories, or adjust permissions to allow the
    directories to be created.

    Your settings are likely OK if you can run this at the command line without
    any errors showing up.  It should just "hang"; push Ctrl-C to quit it.

        ./sphinx-wiki.py

    NOTE: you must be able to run the file as shown above, since that is what
          the PHP code will use to call this file.

5.  Also change the single setting in the "sphinx-wiki.php" file to point to
    the location of this file ("sphinx-wiki.py").

6.  Add the following line to your wiki's "LocalSettings.php" file:
        require_once("$IP/extensions/sphinx-wiki/sphinx-wiki.php");

PRINCIPLE
---------
Mediawiki operates by converting your usual wiki markup to HTML.

The 2 files that make this wiki extension operate by intercepting any text that
appears between <rst> ... </rst> tags in the wiki.  We will call that text the
`rst_text` here.

This rst_text is received by "process-rst.py" (this file), and sent to Sphinx
to be converted to HTML via Sphinx's pickle builder.  That HTML is returned back
to Mediawiki to display.

Special handling is required for images.  Any images used in your code are
assumed to have been uploaded to the wiki *with the same name* as used in the
rst_text.  Sphinx obviously requires to see your images when compiling your
rst_text.  So this code extracts the images from your wiki and makes them
available to Sphinx.

After compiling, the code moves the images to a location on your


CASES WHEN THIS CODE MIGHT NOT WORK FOR YOU
--------------------------------------------

*   You need to cross reference to another part of some RST text in another wiki
    page.
*   You want to include other reStructuredText from another file using the
    ``.. include::`` directive.

USAGE NOTES
-----------

Two options are currently available, shown by example:

    <rst>
    <rst-options: 'toc' = False/>
    <rst-options: 'reset-figures' = False/>

    Your RST code here, etc.

    Images must (currently) be included as:

    .. figure:: images/reactor.png
	    :scale: 40
	    :align: center

    This implies that an image, with the name "reactor.png" must be uploaded
    into the Mediawiki.

    </rst>

The default for both options is `True`, so you can omit that entire line.
The 'toc' option will generate a table of contents, using whatever TOC Sphinx
would have shown.
"""

# Imports
# -------
from __future__ import with_statement
import os
import re
import sys
import errno
import pickle
import platform
import subprocess
import logging.handlers
from hashlib import md5
from urllib2 import urlopen, URLError

# easy_install -U wikitools   (see http://code.google.com/p/python-wikitools/)
from wikitools import wiki, api

# Settings
# =========

# Wiki settings
# -------------
# These are used to take any images out of the wiki.  Mediawiki API must be
# enabled (it is by default) for this to work.  If you visit the api.php page
# below you should get some XML output back.
wiki_api_location = 'http://example.com/w/api.php'
wiki_api_user = 'wiki_username_that_has_api_rights'
wiki_api_password = 'that_users_password'

# Sphinx settings
# ---------------
sphinx_executable = '/usr/local/bin/sphinx-build'

# When Sphinx compiles your file, it will need to see the `conf.py` file, and
# any other custom extensions. These are added as symlinks into each compile
# dir, to avoid duplication. Also, if you make any changes to these files,
# then your wiki pages will be updated if you "touch" them.   At a minimum,
# this list must include 'conf.py' and 'index.rst',
files_for_symlinks = ['conf.py', 'index.rst']

# Where is this extension on your server?
extension_dir = '/var/www/w/extensions/sphinx-wiki/'   # end with trailing slash

# These next few settings have to do with replacing image links in Sphinx's HTML
#
# e.g.  Sphinx : <img src="../_images/images/a.png">
#                          -----------
#
#       replace: <img src="/w/sphinx_images/images/a.png">
#                          -----------------
#
# In this example the underlined parts are searched for and replaced.
#   sphinx_static_dir = '../_images/'
#   static_content_url = '/w/sphinx_images/'

# The first part of the Sphinx output, which is to be replaced
sphinx_static_dir = '../_images'

# The replacement text, as illustrated above.  This is a relative link to a
# location on your server.  E.g. http://example.com/w/sphinx_images/images/a.png
# must resolve and access the image file, "a.png".
static_content_url = '/w/sphinx_images/'

# This is the physical directory on your server where the above image will be
# copied to, after Sphinx has compiled the HTML.
static_content_dir = '/var/www/w/sphinx_images/'


# HTML output preferences
# ------------------------
#
# Append any HTML to the bottom over every page.  For example, I use the code
# below to add a lightbox effect to the images on my site.
#
# Set this to an empty string if you don't require it.
append_html = """\
<script type="text/javascript" src="/media/jquery-1.4.2.min.js"></script>
<script type="text/javascript" src="/media/fancybox/jquery.mousewheel-3.0.2.pack.js"></script>
<script type="text/javascript" src="/media/fancybox/jquery.fancybox-1.3.1.pack.js"></script>
<link rel="stylesheet" type="text/css" href="/media/fancybox/jquery.fancybox-1.3.1.css" media="screen" />
<script type="text/javascript">
            $(document).ready(function() {
                $("a[rel=sphinx_image]").fancybox();
                $("a.embed").fancybox({'hideOnContentClick': true});
            });
</script>
"""

# Other settings
# --------------
# Settings that could be adjusted, but probably shouldn't
compilearea = '_compilearea'  # subdir under extension_dir where we compile RST
rst_filename = 'wiki_rst'     # rst_text is written to this file name
rst_extension = '.rst'        # with this extension
pickle_extension = '.fpickle' # what Sphinx will automatically append

# ADVANCED
# --------
# I often include external source code in my pages (e.g. solutions to tutorials
# and assignments). These are pulled in from a Mercurial repository.  That
# repo must exist somewhere, as a subdir of `compilearea`.  For example:
#
#    local_repo_dir = extension_dir + compilearea + os.sep + 'repo'

# If left empty, then it won't pull/update the repo
local_repo_dir = ''
path_to_mercurial = '/usr/bin/hg'


# Start of code
# ------------------------------------------------------------------------------

# This function modified from Sphinx: ``sphinx.util.osutil``
def ensuredir(path):
    """Ensure that a path exists."""
    try:
        os.makedirs(path)
    except OSError, err:
        # 0 for Jython/Win32
        if err.errno not in [0, getattr(errno, 'EEXIST', 0)]:
            raise

ensuredir(static_content_dir)
ensuredir(extension_dir)

def process_rst_text(rst_text, log_file):
    """
    Receives the `rst_text`; converts it to HTML; handles any images.
	"""
    # Note: the `rst_text` is a string, not a list of strings.

    # 0. Hash of the text: used to create a unique directory where that file
    #    is compiled by Sphinx; if we just compiled in a single directory, then
    #    we would not be able to handle multiple users editing on the wiki.
    text_hash = md5(rst_text).hexdigest()
    log_file.debug('Hash is = %s; snippet = %s' % (text_hash,
                                        rst_text[50:150].replace('\n',';')))

    # 1. Pre-process the raw RST test: process any options that are given. E.g.:

    #  <rst-options: 'toc' = False/>
    #  <rst-options: 'reset-figures' = False/>

    options_re = re.compile(r'<rst-options(\s)*:(\s)(.*)/>')
    options_dict = {'toc': True, 'reset-figures': True}  # defaults
    option = []
    for option in options_re.finditer(rst_text):
        start, end = option.span()
        log_file.debug('Found option: %s' % rst_text[start:end])
        rst_text = rst_text[0:start] + ' '*(end-start) + rst_text[end:]
        option, value = option.groups()[2].split('=')
        if option.strip(" '").lower() == 'toc':
            if value.strip(" '").lower() == 'false':
                options_dict['toc'] = False
        elif option.strip(" '").lower() == 'reset-figures':
            if value.strip(" '").lower() == 'false':
                options_dict['reset-figures'] = False

    # Clean start of rst_text (usually where the options appear)
    if option:
        rst_text = rst_text.strip()

    # 2. Write the RST text to the compile area on the webserver
    base_dir = extension_dir + compilearea
    # This is where the document will be compiled
    rst_dir = base_dir + os.sep + text_hash
    ensuredir(rst_dir)
    rst_file = file(rst_dir + os.sep + rst_filename + rst_extension, 'w')
    rst_file.write(rst_text)
    rst_file.close()
    log_file.debug('Wrote RST to text file')

    # 3. Find all images used in the RST text, extract them from the wiki and
    #    place them in an "images" directory that Sphinx can see.
    image_storage = rst_dir + os.sep + 'images'
    ensuredir(image_storage)
    re_figure = re.compile(r'(\s)*..(\s)*figure::(\s)*images\/(.*)')
    figures = re_figure.findall(rst_text)
    for figure in figures:
        figure_name = figure[3]

        # Sphinx allows a wildcard specification: replace it with png'
        if figure_name[-1] == '*':
            figure_name = figure_name[0:figure_name.find('*')] + 'png'

        # Only download images we don't already have, unless the reset-figures
        # option is True
        if figure_name not in os.listdir(image_storage) or \
                                                  options_dict['reset-figures']:

            log_file.debug('Extracting figure from wiki: ' + figure_name)

            site = wiki.Wiki(wiki_api_location)
            site.login(username=wiki_api_user, password=wiki_api_password,
                                                                 remember=True)
            params = {'action':'query', 'titles': 'File:' + figure_name,
                      'prop': 'imageinfo', 'iiprop': 'url'}
            request = api.APIRequest(site, params)
            res = request.query()

            page_id = res['query']['pages'].keys()[0]
            # Image not uploaded yet!
            if page_id == '-1':
                log_file.warning('Figure "%s" not available yet in wiki' % \
                                                                   figure_name)
                continue

            image_url = res['query']['pages'][page_id]['imageinfo'][0]['url']

            with open(image_storage + os.sep + figure_name, 'wb') as im_file:
                try:
                    u = urlopen(image_url)
                except URLError:
                    exit(-3)

                minor_version = platform.python_version_tuple()[1]
                if minor_version == '5':
                    if u.code == 200:
                        im_file.write(u.read())
                elif minor_version == '6':
                    if u.getcode() == 200:
                        im_file.write(u.read())

        else:
            log_file.debug('Figure not required for download: ' + figure_name)

    # 4. Pull all code snippets from the Mercurial repo
    if local_repo_dir:
        pull_command = [path_to_mercurial, 'pull']
        update_command = [path_to_mercurial, 'update']
        try:
            subprocess.check_call(pull_command, stdout=subprocess.PIPE,
                                  cwd=local_repo_dir)
            subprocess.check_call(update_command, stdout=subprocess.PIPE,
                                  cwd=local_repo_dir)
        except (OSError, subprocess.CalledProcessError):
            log_file.debug('failed: %s' % sys.exc_info()[0])
            print (('<span style="color:red">Could not pull and update the '
                     'repository; please report this problem to site '
                     'administrator.</span>'))
        log_file.debug('Successfully updated the repository.')

    # 5. Symlink the ``conf.py`` file and any other files required
    for file_req in files_for_symlinks:
        if not os.path.exists(rst_dir + os.sep + file_req):
            os.symlink(base_dir + os.sep + file_req,
                       rst_dir + os.sep + file_req)

    # 6. Call Sphinx to compile the RST code.
    sphinx_command = [sphinx_executable, '-b', 'pickle', '-d',
                      '_build/doctrees', '.', '_build/pickle']
    try:
        subprocess.check_call(sphinx_command, stdout=subprocess.PIPE,
                              cwd=rst_dir)
    except subprocess.CalledProcessError:
        log_file.debug('An error occurred while calling Sphinx: %s' % \
                                                            str(sphinx_command))
        print (('An error occurred when compiling the RST code to HTML.'
                 'Please email the site administrator.'))
        exit(-2)
    log_file.debug('Called Sphinx; successfully pickled the HTML.')


    # 7. Read the HTML out of the pickle file; return it with the TOC at the top
    if options_dict['toc']:
        pickle_f_toc = os.sep.join([rst_dir, '_build', 'pickle',
                                    'index' + pickle_extension])
        ensuredir(os.sep.join([rst_dir, '_build', 'pickle']))
        f = file(pickle_f_toc, 'r')
        obj = pickle.load(f)
        f.close()
        toc_pickle = obj['body'].encode('utf-8')
        log_file.debug('Successfully read the TOC pickle file: ' + pickle_f_toc)

        # Replace Sphinx's class name with our own.  Add appropriate CSS
        # e.g. to the "MediaWiki:Common.css" page in your wiki.
        toc_pickle = re.sub('reference external',
                            'reference-external-sphinx', toc_pickle)

        # Remove the relative link from the Sphinx TOC
        toc_pickle = re.sub(rst_filename + r'/', '', toc_pickle)

        # The TOC is wrapped in some Javascript to allow show/hide option
        toc = (('<table id="toc" class="toc" summary="Contents">\n'
                '<tr>\n<td>\n\t<div id="toctitle"><h2>Contents</h2></div>\n  %s'
                '</td>\n</tr>\n</table>\n'
                '<script type="text/javascript"> if (window.showTocToggle) '
                '{ var tocShowText = "show"; var tocHideText = "hide"; '
                'showTocToggle(); } </script>') % (toc_pickle))
    else:
        toc = ''

    pickle_f = os.sep.join([rst_dir, '_build', 'pickle',
                            rst_filename + pickle_extension])

    f = file(pickle_f, 'r')
    obj = pickle.load(f)
    f.close()
    html = toc + obj['body'].encode('utf-8')


    # 8. Process the HTML to replace the link source for images.  Two cases:

    # Sphinx output: <img src="../_images/...
    # Replaced with: <img src="/w/sphinx_images/...
    replacement_text = 'src="' + static_content_url
    html = re.sub('src="' + sphinx_static_dir, replacement_text, html)

    # Sphinx output: <img href="../_images/...
    # Replaced with: <img href="/w/sphinx_images/...
    replacement_text = r'rel="sphinx_image"'  # required for the jQuery selector
    replacement_text += 'href="' +  static_content_url
    html = re.sub('href="' + sphinx_static_dir, replacement_text, html)

    # 9. Copy any images and equations to the static media location on server
    copy_command = ['cp', '-ru',
                    os.sep.join([rst_dir, '_build', 'pickle', '_images', '.']),
                    static_content_dir]
    ensuredir(os.sep.join([rst_dir, '_build', 'pickle', '_images']))

    log_file.debug('image copy command = %s' % copy_command)
    try:
        subprocess.check_call(copy_command, stdout=subprocess.PIPE,
                              cwd=rst_dir)
    except subprocess.CalledProcessError:
        print (('An error occurred when copying over the image data to the '
                 'static web-directory; please email the site administrator.'))
        exit(-2)
    log_file.debug('Moved static image content to the media directory.')

    # 10. Finished!
    return html

if __name__ == '__main__':
    # 0. Setup logging: isn't there a shorter way to do this?
    LOG_FILENAME = extension_dir + 'log-sphinx-wiki.log'
    my_logger = logging.getLogger('sphinx-wiki')
    my_logger.setLevel(logging.DEBUG)  # TODO: change the level to INFO
    fh = logging.handlers.RotatingFileHandler(LOG_FILENAME,
                                              maxBytes=2000000,
                                              backupCount=5)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(formatter)
    my_logger.addHandler(fh)
    my_logger.debug('A new call to the sphinx-wiki script')

    # 1. Reads from stdin: this is what PHP passes into the script
    incoming = sys.stdin.read()

    # 2. Convert RST to HTML, using Sphinx to return the HTML
    html_from_sphinx = process_rst_text(incoming, my_logger) + append_html

    # 3. Print the HTML to stdout; picked up by PHP and displayed in the wiki
    print(html_from_sphinx)


