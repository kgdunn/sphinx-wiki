<?php
# reStructuredText to HTML using Sphinx

# I got the layout for this PHP code from somewhere; I think it was
# from http://www.mediawiki.org/wiki/Extension:RstToHtml

# Setting (only 1)
# ================
$process_rst_file = '/var/www/w/extensions/sphinx-wiki/sphinx-wiki.py';

$wgExtensionCredits['parserhook'][] = array(
    'name' => 'sphinx-wiki',
    'author' => 'Kevin Dunn',
    'url' => 'http://connectmv.com',
    'description' => 'This extension parses ReStructured Text (RST) through Sphinx and returns the HTML.');

$wgExtensionFunctions[] = 'RstToHtmlSetup';

function RstToHtmlSetup()
{
    global $wgParser;
    $wgParser->setHook('rst', 'HTMLrender');
}

function HTMLrender($input, $args, $parser)
{
    global $process_rst_file;

    if (count($args))
    {
        return "<strong class='error'>" .
               "sphinx-wiki extension: arguments not supported" .
               "</strong>";
    }

    # If pipe errors are reported, enable output to the file.
    # But make certain the file doesn't already exist or else
    # the webserver may not have permission to create it.
    $io_desc = array(
            0 => array('pipe', 'r'),
            1 => array('pipe', 'w'));

    $res = proc_open($process_rst_file, $io_desc, $pipes, '/tmp', NULL);

    if (is_resource($res))
    {
        fwrite($pipes[0], $input);
        fclose($pipes[0]);
        $html = stream_get_contents($pipes[1]);
        fclose($pipes[1]);
    }
    else
    {
        $html = "<strong class='error'>" .
                "sphinx-wiki extension: error opening pipe" .
                "</strong>";
    }
    return $html;
}

