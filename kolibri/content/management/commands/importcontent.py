import os

from django.conf import settings
from django.core.management.base import CommandError
from django.db.models import Sum
from kolibri.tasks.management.commands.base import AsyncCommand
from requests.exceptions import HTTPError

from ...models import LocalFile, ContentNode
from ...utils import annotation, paths, transfer

# constants to specify the transfer method to be used
DOWNLOAD_METHOD = "download"
COPY_METHOD = "copy"


class Command(AsyncCommand):

    def add_arguments(self, parser):
        # let's save the parser in case we need to print a help statement
        self._parser = parser

        # we want two groups of arguments. One group is when the
        # 'importcontent disk' command is given, where we'll expect a file
        # directory to be given. Another is the 'importcontent network'
        # command to be given, where we'll expect a channel.

        # However, some optional arguments apply to both groups. Add them here!
        node_ids_help_text = """
        Specify one or more node IDs to import. Only the files associated to those node IDs will be imported.

        e.g.

        kolibri manage importcontent --node_ids <id1>,<id2>, [<ids>,...] {network, disk} <channel id>
        """
        parser.add_argument(
            "--node_ids", "-n",
            # Split the comma separated string we get, into a list of strings
            type=lambda x: x.split(","),
            default=[],
            required=False,
            dest="node_ids",
            help=node_ids_help_text,
        )

        exclude_node_ids_help_text = """
        Specify one or more node IDs to exclude. Files associated to those node IDs will be not be imported.

        e.g.

        kolibri manage importcontent --exclude_node_ids <id1>,<id2>, [<ids>,...] {network, disk} <channel id>
        """
        parser.add_argument(
            "--exclude_node_ids",
            # Split the comma separated string we get, into a list of string
            type=lambda x: x.split(","),
            default=[],
            required=False,
            dest="exclude_node_ids",
            help=exclude_node_ids_help_text
        )

        # to implement these two groups of commands and their corresponding
        # arguments, we'll need argparse.subparsers.
        subparsers = parser.add_subparsers(dest='command', help="The following subcommands are available.")

        # the network command has a channel id required positional argument,
        # and some optional content_id arguments.

        # TODO: implement a --content-domain parameter, for optionally
        # specifying the domain for the curation server.

        # Note: cmd should be the management command instance, as though the
        # interface for adding arguments is argparse, Django overrides the
        # parser object with its own thing, hence why we need to add cmd. See
        # http://stackoverflow.com/questions/36706220/is-it-possible-to-create-subparsers-in-a-django-management-command
        network_subparser = subparsers.add_parser(
            name='network',
            cmd=self,
            help="Download the given channel through the network.",
        )
        network_subparser.add_argument('channel_id', type=str)

        default_studio_url = settings.CENTRAL_CONTENT_DOWNLOAD_BASE_URL
        network_subparser.add_argument(
            "--baseurl",
            type=str,
            default=default_studio_url,
            dest="baseurl",
        )

        disk_subparser = subparsers.add_parser(
            name='disk',
            cmd=self,
            help='Copy the content from the given folder.'
        )
        disk_subparser.add_argument('channel_id', type=str)
        disk_subparser.add_argument('directory', type=str)

    def download_content(self, channel_id, node_ids=None, exclude_node_ids=None, baseurl=None):
        self._transfer(DOWNLOAD_METHOD, channel_id, node_ids=node_ids, exclude_node_ids=exclude_node_ids, baseurl=baseurl)

    def copy_content(self, channel_id, path, node_ids=None, exclude_node_ids=None):
        self._transfer(COPY_METHOD, channel_id, path=path, node_ids=node_ids, exclude_node_ids=exclude_node_ids)

    def _get_leaves_ids(self, node_ids):
        leaf_node_ids = []
        for node_id in node_ids:
            node_leaves = ContentNode.objects.get(pk=node_id).get_descendants(include_self=True).filter(children__isnull=True).values_list('id', flat=True)
            leaf_node_ids += node_leaves
        return leaf_node_ids

    def _transfer(self, method, channel_id, path=None, node_ids=None, exclude_node_ids=None, baseurl=None):  # noqa: max-complexity=16

        files_to_download = LocalFile.objects.filter(files__contentnode__channel_id=channel_id, available=False)

        if node_ids:
            leaf_node_ids = self._get_leaves_ids(node_ids)
            files_to_download = files_to_download.filter(files__contentnode__in=leaf_node_ids)

        if exclude_node_ids:
            exclude_leaf_node_ids = self._get_leaves_ids(exclude_node_ids)
            files_to_download = files_to_download.exclude(files__contentnode__in=exclude_leaf_node_ids)

        # Make sure the files are unique, to avoid duplicating downloads
        files_to_download = files_to_download.distinct()

        total_bytes_to_transfer = files_to_download.aggregate(Sum('file_size'))['file_size__sum'] or 0

        downloaded_files = []
        file_checksums_to_annotate = []

        with self.start_progress(total=total_bytes_to_transfer) as overall_progress_update:

            for f in files_to_download:

                if self.is_cancelled():
                    break

                filename = f.get_filename()
                dest = paths.get_content_storage_file_path(filename)

                # if the file already exists, add its size to our overall progress, and skip
                if os.path.isfile(dest) and os.path.getsize(dest) == f.file_size:
                    overall_progress_update(f.file_size)
                    file_checksums_to_annotate.append(f.id)
                    continue

                # determine where we're downloading/copying from, and create appropriate transfer object
                if method == DOWNLOAD_METHOD:
                    url = paths.get_content_storage_remote_url(filename, baseurl=baseurl)
                    filetransfer = transfer.FileDownload(url, dest)
                elif method == COPY_METHOD:
                    srcpath = paths.get_content_storage_file_path(filename, datafolder=path)
                    filetransfer = transfer.FileCopy(srcpath, dest)

                try:

                    with filetransfer:

                        with self.start_progress(total=filetransfer.total_size) as file_dl_progress_update:

                            for chunk in filetransfer:
                                if self.is_cancelled():
                                    filetransfer.cancel()
                                    break
                                length = len(chunk)
                                overall_progress_update(length)
                                file_dl_progress_update(length)
                            else:
                                # If the for loop didn't break, add this to downloaded files.
                                downloaded_files.append(dest)

                    file_checksums_to_annotate.append(f.id)

                except HTTPError:
                    overall_progress_update(f.file_size)

            if self.is_cancelled():
                # Cancelled, clean up any already downloading files.
                for dest in downloaded_files:
                    os.remove(dest)
                self.cancel()
            else:
                annotation.set_availability(file_checksums_to_annotate)

    def handle_async(self, *args, **options):
        if options['command'] == 'network':
            self.download_content(options["channel_id"],
                                  node_ids=options["node_ids"],
                                  exclude_node_ids=options['exclude_node_ids'],
                                  baseurl=options["baseurl"])
        elif options['command'] == 'disk':
            self.copy_content(options["channel_id"],
                              options["directory"],
                              node_ids=options["node_ids"],
                              exclude_node_ids=options["exclude_node_ids"])
        else:
            self._parser.print_help()
            raise CommandError("Please give a valid subcommand. You gave: {}".format(options["command"]))
